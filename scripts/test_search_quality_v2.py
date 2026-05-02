"""검색 품질 v2 평가 — 1200+ 쿼리, source 별·도메인별·adversarial 별도 분석.

확장:
  - source 별 메트릭 (filename / stt / caption / natural_lang / adversarial)
  - Recall@5/10/20, MRR, Top-1, 응답시간 분포
  - 실패 쿼리 분류 (도메인 미스매치 / dense 약함 / dedup 손실)
  - HTML 리포트 (선택)

사용:
  python scripts/test_search_quality_v2.py
  python scripts/test_search_quality_v2.py --top-k 20 --json out.json
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

API_BASE = "http://127.0.0.1:5001"
DEFAULT_GT = Path(__file__).parent / "_ground_truth_v2.json"


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


# ── Direct engine 모드 (백엔드 없이) ──────────────────────────────────
_engine_inst = None


def _get_engine():
    global _engine_inst
    if _engine_inst is None:
        import os
        os.environ.setdefault("TRICHEF_USE_RERANKER", "0")
        backend_path = str(Path(__file__).resolve().parents[1] / "App" / "backend")
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)
        from services.trichef.unified_engine import TriChefEngine
        _engine_inst = TriChefEngine()
    return _engine_inst


_DOMAIN_TO_KIND = {"doc": "doc_page", "image": "image", "video": "movie", "audio": "music"}


def search_direct(q: str, top_k: int = 10, dtype: str | None = None) -> dict:
    """백엔드 없이 unified_engine 직접 호출 — 정확한 routes/search.py 동작 X
    (도메인 quota 보장, dedup, rerank, location 미적용)."""
    eng = _get_engine()
    t0 = time.time()
    results: list[dict] = []
    if dtype:
        kind = _DOMAIN_TO_KIND.get(dtype, dtype)
        if kind in ("movie", "music"):
            for r in eng.search_av(q, kind, topk=top_k):
                results.append({"file_name": r.file_name, "file_type": dtype,
                                "confidence": r.confidence, "trichef_id": r.file_path})
        else:
            for r in eng.search(q, kind, topk=top_k,
                                use_lexical=True, use_asf=True, pool=200):
                fname = (r.id.replace("\\", "/").rsplit("/", 1)[-1])
                # Doc id = "page_images/<stem>/p####.jpg" → stem 사용
                if r.id.startswith("page_images/"):
                    stem = r.id.split("/", 2)[1]
                    fname = stem + ".pdf"
                results.append({"file_name": fname, "file_type": dtype,
                                "confidence": r.confidence, "trichef_id": r.id})
    else:
        # 통합 검색 — 4 도메인 quota 보장 (search.py 와 유사)
        quota = max(1, top_k // 4)
        for kind, ftype in (("doc_page", "doc"), ("image", "image"),
                            ("movie", "video"), ("music", "audio")):
            try:
                if kind in ("movie", "music"):
                    hits = eng.search_av(q, kind, topk=top_k)
                    for r in hits[:quota]:
                        results.append({"file_name": r.file_name, "file_type": ftype,
                                        "confidence": r.confidence})
                else:
                    hits = eng.search(q, kind, topk=top_k,
                                      use_lexical=True, use_asf=True, pool=200)
                    for r in hits[:quota]:
                        fname = r.id.replace("\\", "/").rsplit("/", 1)[-1]
                        if r.id.startswith("page_images/"):
                            fname = r.id.split("/", 2)[1]
                        results.append({"file_name": fname, "file_type": ftype,
                                        "confidence": r.confidence})
            except Exception:
                pass
        results.sort(key=lambda r: -r.get("confidence", 0))
    return {"results": results[:top_k], "_elapsed": time.time() - t0}


def evaluate_one(qo: dict, top_k: int, type_filter: bool, direct: bool = False) -> dict:
    q   = qo["query"]
    dom = qo.get("domain")
    expected = set(b.lower() for b in qo.get("expected_basenames", []))
    dtype = dom if type_filter else None
    try:
        if direct:
            data = search_direct(q, top_k, dtype)
        else:
            data = search(q, top_k, dtype)
    except Exception as e:
        return {"query": q, "domain": dom, "source": qo.get("source"),
                "error": str(e)[:80]}

    results = data.get("results", [])
    elapsed = data.get("_elapsed", 0)
    positions = []
    for i, r in enumerate(results, 1):
        fn = (r.get("file_name") or "").lower()
        if fn in expected:
            positions.append(i)

    n_expected = len(expected)
    hit  = len(positions) > 0
    coverage = len(positions) / min(n_expected, top_k) if n_expected else 0
    mrr  = (1.0 / positions[0]) if positions else 0.0
    top1 = (positions[0] == 1) if positions else False
    fname_count = Counter((r.get("file_name") or "").lower() for r in results)
    n_dup = sum(c - 1 for c in fname_count.values() if c > 1)

    return {
        "query": q, "domain": dom, "source": qo.get("source"),
        "n_expected": n_expected, "hit": hit, "coverage": coverage,
        "mrr": mrr, "top1": top1, "first_pos": positions[0] if positions else None,
        "n_results": len(results), "n_dup": n_dup, "elapsed": elapsed,
        "first_result": (results[0].get("file_name") or "")[:60] if results else None,
    }


def report_table(rows: list[dict], group_key: str, title: str) -> None:
    print(f"\n{title}")
    print("-" * 100)
    print(f"{'그룹':<22} {'쿼리':<6} {'Recall@K':<11} {'Coverage':<10} "
          f"{'MRR':<7} {'Top-1':<8} {'중복':<6} {'평균응답':<10}")
    print("-" * 100)
    by_grp = defaultdict(list)
    for r in rows:
        if "error" in r:
            continue
        k = r.get(group_key) or "(none)"
        by_grp[k].append(r)
    for grp in sorted(by_grp):
        rs = by_grp[grp]
        n  = len(rs)
        hit = sum(1 for r in rs if r["hit"])
        cov = sum(r["coverage"] for r in rs) / n
        mrr = sum(r["mrr"] for r in rs) / n
        t1  = sum(1 for r in rs if r["top1"])
        dup = sum(r["n_dup"] for r in rs)
        avg_t = sum(r["elapsed"] for r in rs) / n
        print(f"{grp:<22} {n:<6} {hit/n*100:>5.0f}% ({hit:>3}) "
              f"{cov*100:>6.0f}%   {mrr:<7.3f} {t1/n*100:>5.0f}%   "
              f"{dup:<6} {avg_t:<10.2f}s")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--type-filter", action="store_true")
    parser.add_argument("--ground-truth", default=str(DEFAULT_GT))
    parser.add_argument("--json", help="결과 JSON 저장")
    parser.add_argument("--limit", type=int, help="처음 N 쿼리만 (개발용)")
    parser.add_argument("--direct", action="store_true",
                        help="백엔드 없이 unified_engine 직접 호출")
    args = parser.parse_args()

    gt_path = Path(args.ground_truth)
    if not gt_path.exists():
        print(f"[ERROR] ground truth 없음: {gt_path}")
        return 2

    queries = json.loads(gt_path.read_text(encoding="utf-8"))
    if args.limit:
        queries = queries[:args.limit]
    print(f"ground truth 쿼리: {len(queries)}", flush=True)

    if args.direct:
        print("[direct] 백엔드 없이 unified_engine 직접 호출 (도메인 quota·dedup·rerank 미적용)",
              flush=True)
    else:
        try:
            urllib.request.urlopen(f"{API_BASE}/api/files/stats", timeout=3)
        except Exception as e:
            print(f"[ERROR] 백엔드({API_BASE}) 응답 없음: {e}")
            print(f"  → --direct 옵션으로 백엔드 없이 평가 가능")
            return 2

    print(f"평가 시작 (top_k={args.top_k}, type_filter={args.type_filter}, "
          f"direct={args.direct})", flush=True)
    results: list[dict] = []
    for i, qo in enumerate(queries, 1):
        if i % 50 == 0:
            print(f"  진행: {i}/{len(queries)}", flush=True)
        results.append(evaluate_one(qo, args.top_k, args.type_filter, args.direct))

    # 도메인별
    report_table(results, "domain",  "===== 도메인별 메트릭 =====")
    # 소스별
    report_table(results, "source",  "===== 소스(쿼리 종류) 별 메트릭 =====")

    # 도메인 × 소스 cross-tab
    print("\n===== 도메인 × 소스 — Recall@K =====")
    print("-" * 70)
    cell_recall = defaultdict(lambda: [0, 0])
    for r in results:
        if "error" in r: continue
        k = (r.get("domain") or "?", r.get("source") or "?")
        cell_recall[k][0] += 1 if r["hit"] else 0
        cell_recall[k][1] += 1
    sources = sorted(set(s for _, s in cell_recall))
    domains = sorted(set(d for d, _ in cell_recall))
    print(f"{'':<8}", end="")
    for s in sources:
        print(f"{s[:14]:<16}", end="")
    print()
    for d in domains:
        print(f"{d:<8}", end="")
        for s in sources:
            hits, tot = cell_recall.get((d, s), [0, 0])
            cell = f"{hits}/{tot}" if tot else "-"
            print(f"{cell:<16}", end="")
        print()

    # 응답시간 분포
    elapseds = sorted(r.get("elapsed", 0) for r in results if "elapsed" in r)
    if elapseds:
        p50 = elapseds[len(elapseds)//2]
        p95 = elapseds[int(len(elapseds)*0.95)]
        print(f"\n응답시간: p50={p50:.2f}s p95={p95:.2f}s max={elapseds[-1]:.2f}s "
              f"평균={sum(elapseds)/len(elapseds):.2f}s")

    # 실패 쿼리 분석
    failures = [r for r in results
                if r.get("n_expected", 0) > 0 and not r.get("hit")]
    failures.sort(key=lambda r: -r.get("n_expected", 0))

    fail_by_src = Counter(r["source"] for r in failures)
    fail_by_dom = Counter(r["domain"] for r in failures)
    print(f"\n총 실패 쿼리: {len(failures)}/{len(results)}")
    print(f"  도메인별 실패: {dict(fail_by_dom)}")
    print(f"  소스별 실패:   {dict(fail_by_src)}")

    print(f"\n실패 쿼리 상위 20:")
    for r in failures[:20]:
        first = r.get("first_result") or "(없음)"
        print(f"  [{r['domain']:<5}|{r['source'][:12]:<12}] "
              f"{r['query'][:30]:<30} expected={r.get('n_expected', 0)} "
              f"first={first}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n전체 결과 → {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
