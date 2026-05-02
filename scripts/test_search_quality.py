"""검색 품질 종합 평가 — ground_truth_auto.json 기반.

각 쿼리에 대해:
  1. /api/search 호출 (도메인 미지정, type 지정 모두)
  2. top-K 결과를 expected_basenames 와 비교
  3. Recall@5/10/20, MRR, Top-1, 응답시간, 중복률 측정

도메인별 + 전체 요약 + 실패 쿼리 top-N 출력.

사용:
  python scripts/test_search_quality.py
  python scripts/test_search_quality.py --top-k 20 --json out.json
  python scripts/test_search_quality.py --type-filter   # 각 쿼리 type=domain 호출
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

API_BASE = "http://127.0.0.1:5001"
GT_FILE  = Path(__file__).parent / "_ground_truth_auto.json"


def search(q: str, top_k: int = 10, dtype: str | None = None) -> dict:
    params: dict = {"q": q, "top_k": top_k}
    if dtype:
        params["type"] = dtype
    url = f"{API_BASE}/api/search?" + urllib.parse.urlencode(params)
    t0 = time.time()
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read())
    data["_elapsed"] = time.time() - t0
    return data


def evaluate_one(query_obj: dict, top_k: int, type_filter: bool) -> dict:
    q   = query_obj["query"]
    dom = query_obj.get("domain")
    expected = set(b.lower() for b in query_obj.get("expected_basenames", []))

    dtype = dom if type_filter else None
    try:
        data = search(q, top_k, dtype)
    except Exception as e:
        return {"query": q, "domain": dom, "error": str(e)[:80]}

    results = data.get("results", [])
    elapsed = data.get("_elapsed", 0)

    # hit positions (1-based)
    positions: list[int] = []
    for i, r in enumerate(results, 1):
        fn = (r.get("file_name") or "").lower()
        if fn in expected:
            positions.append(i)

    n_expected = len(expected)
    # Recall@K: top-K 안에 정답이 1개 이상 = hit
    hit  = len(positions) > 0
    # 정답 회수율 = (top-K 안 정답 수) / 총 정답 수 (capped at K)
    coverage = len(positions) / min(n_expected, top_k) if n_expected else 0
    mrr  = (1.0 / positions[0]) if positions else 0.0
    top1 = (positions[0] == 1) if positions else False

    # 중복률
    fname_count = Counter((r.get("file_name") or "").lower() for r in results)
    n_dup = sum(c - 1 for c in fname_count.values() if c > 1)

    # 도메인 분포
    dom_dist = Counter(r.get("file_type") for r in results)

    return {
        "query":      q,
        "domain":     dom,
        "n_expected": n_expected,
        "hit":        hit,
        "coverage":   coverage,
        "mrr":        mrr,
        "top1":       top1,
        "first_pos":  positions[0] if positions else None,
        "n_results":  len(results),
        "n_dup":      n_dup,
        "elapsed":    elapsed,
        "domain_dist": dict(dom_dist),
        "first_result": (results[0].get("file_name") or "")[:60] if results else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--json", help="결과 JSON 저장 경로")
    parser.add_argument("--type-filter", action="store_true",
                        help="각 쿼리 type=<domain> 으로 호출 (도메인별 정밀 평가)")
    parser.add_argument("--ground-truth", default=str(GT_FILE))
    args = parser.parse_args()

    gt_path = Path(args.ground_truth)
    if not gt_path.exists():
        print(f"[ERROR] ground truth 파일 없음: {gt_path}")
        print("  먼저: python scripts/build_ground_truth.py")
        return 2

    queries = json.loads(gt_path.read_text(encoding="utf-8"))
    print(f"ground truth 쿼리: {len(queries)}")

    # backend health
    try:
        urllib.request.urlopen(f"{API_BASE}/api/files/stats", timeout=3)
    except Exception as e:
        print(f"[ERROR] 백엔드({API_BASE}) 응답 없음: {e}")
        return 2

    # 평가 실행
    print(f"\n{'쿼리 평가 중':<20} top_k={args.top_k}, "
          f"type_filter={args.type_filter}")
    results: list[dict] = []
    for i, qo in enumerate(queries, 1):
        if i % 10 == 0:
            print(f"  진행: {i}/{len(queries)}")
        results.append(evaluate_one(qo, args.top_k, args.type_filter))

    # 도메인별 메트릭
    by_dom: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        if "error" in r:
            continue
        by_dom[r["domain"]].append(r)

    print("\n" + "=" * 80)
    print(f"검색 품질 종합 보고 (top_k={args.top_k})")
    print("=" * 80)
    print(f"{'도메인':<8} {'쿼리':<6} {'Recall@K':<10} {'Coverage':<10} "
          f"{'MRR':<7} {'Top-1':<8} {'중복':<6} {'평균응답':<10}")
    print("-" * 80)
    grand = {"total": 0, "hit": 0, "coverage_sum": 0, "mrr_sum": 0,
             "top1": 0, "dup": 0, "elapsed_sum": 0}
    for dom in sorted(by_dom):
        rs = by_dom[dom]
        n  = len(rs)
        hit = sum(1 for r in rs if r["hit"])
        cov = sum(r["coverage"] for r in rs) / n
        mrr = sum(r["mrr"] for r in rs) / n
        t1  = sum(1 for r in rs if r["top1"])
        dup = sum(r["n_dup"] for r in rs)
        avg_t = sum(r["elapsed"] for r in rs) / n
        print(f"{dom:<8} {n:<6} {hit/n*100:>5.0f}% ({hit:>3}) "
              f"{cov*100:>6.0f}%   {mrr:<7.3f} {t1/n*100:>5.0f}%   "
              f"{dup:<6} {avg_t:<10.2f}s")
        grand["total"]        += n
        grand["hit"]          += hit
        grand["coverage_sum"] += cov * n
        grand["mrr_sum"]      += mrr * n
        grand["top1"]         += t1
        grand["dup"]          += dup
        grand["elapsed_sum"]  += avg_t * n

    print("-" * 80)
    n = grand["total"]
    if n > 0:
        print(f"{'전체':<8} {n:<6} "
              f"{grand['hit']/n*100:>5.0f}% ({grand['hit']:>3}) "
              f"{grand['coverage_sum']/n*100:>6.0f}%   "
              f"{grand['mrr_sum']/n:<7.3f} "
              f"{grand['top1']/n*100:>5.0f}%   "
              f"{grand['dup']:<6} "
              f"{grand['elapsed_sum']/n:<10.2f}s")

    # 실패 쿼리 (hit=False 또는 expected 가 있는데 1건도 없음) top-15
    failures = [r for r in results
                if r.get("n_expected", 0) > 0 and not r.get("hit")]
    failures.sort(key=lambda r: -r.get("n_expected", 0))
    print(f"\n실패 쿼리 ({len(failures)}건) — 상위 15:")
    for r in failures[:15]:
        first = r.get("first_result") or "(없음)"
        print(f"  [{r['domain']:<5}] {r['query']:<25} "
              f"expected={r.get('n_expected', 0)} "
              f"first={first}")

    # 응답시간 p50/p95
    elapseds = sorted(r.get("elapsed", 0) for r in results if "elapsed" in r)
    if elapseds:
        p50 = elapseds[len(elapseds) // 2]
        p95 = elapseds[int(len(elapseds) * 0.95)]
        print(f"\n응답시간: p50={p50:.2f}s, p95={p95:.2f}s, "
              f"max={elapseds[-1]:.2f}s")

    # JSON 출력
    if args.json:
        Path(args.json).write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n전체 결과 → {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
