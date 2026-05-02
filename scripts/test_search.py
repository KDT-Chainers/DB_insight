"""검색 자동 검증 스크립트 — 인덱싱 완료 후 즉시 실행.

사용:
    python scripts/test_search.py
    python scripts/test_search.py --queries my_queries.json
    python scripts/test_search.py --top-k 5 --json out.json

각 쿼리에 대해:
  1. /api/search 호출 (도메인 무지정)
  2. top-K 결과의 confidence / dense / lexical / asf / rerank_score 출력
  3. location (page / timestamp) 부착 여부 확인
  4. 응답 시간 측정

출력:
  - 쿼리별 표 형태 결과
  - 종합: 평균 응답 시간, 성공율, 도메인 분포

요구사항:
  - 백엔드 (http://127.0.0.1:5001) 가 동작 중이어야 함
  - GPU 사용 X — API 호출만 (병렬 안전)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_BASE = "http://127.0.0.1:5001"

# 기본 검증 쿼리 — 도메인 다양성 + 한국어/영어 혼합.
DEFAULT_QUERIES = [
    "삼성 지속가능 보고서",
    "FAO 식량가격지수",
    "AI 시대 일자리 변화",
    "한국 경제 위기",
    "machine learning",
    "김어준 검사",
    "다스뵈이다 트럼프",
    "스마트폰 없이 여행",
    "박태웅 의장",
    "복지 정책",
]


def fetch_search(query: str, top_k: int = 5, type_filter: str = "",
                 timeout: float = 30.0) -> tuple[float, dict | None, str | None]:
    """단일 검색 호출. 반환: (응답시간초, JSON, 에러메시지)."""
    qs = {"q": query, "top_k": str(top_k)}
    if type_filter:
        qs["type"] = type_filter
    url = f"{API_BASE}/api/search?{urllib.parse.urlencode(qs)}"
    t0 = time.time()
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
        elapsed = time.time() - t0
        return elapsed, data, None
    except urllib.error.HTTPError as e:
        return time.time() - t0, None, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return time.time() - t0, None, f"{type(e).__name__}: {e}"


def fmt_score(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        return f"{v:.3f}"
    return str(v)[:10]


def print_result(query: str, idx: int, total: int, elapsed: float,
                 data: dict | None, error: str | None, top_k: int) -> dict:
    """단일 쿼리 결과 출력 + 요약 dict 반환."""
    print(f"\n[{idx}/{total}] '{query}'  ({elapsed:.2f}s)")
    print("-" * 80)
    summary = {
        "query": query,
        "elapsed_sec": round(elapsed, 3),
        "ok": error is None,
        "error": error,
        "result_count": 0,
        "domains": {},
        "top_confidence": None,
    }
    if error:
        print(f"  ❌ ERROR: {error}")
        return summary
    results = data.get("results", []) if data else []
    summary["result_count"] = len(results)

    for r in results[:top_k]:
        dom = r.get("file_type") or r.get("domain") or "?"
        summary["domains"][dom] = summary["domains"].get(dom, 0) + 1
        name = (r.get("file_name") or r.get("id", ""))[:40]
        conf = fmt_score(r.get("confidence"))
        dense = fmt_score(r.get("dense"))
        lex = fmt_score(r.get("lexical"))
        asf = fmt_score(r.get("asf"))
        rer = fmt_score(r.get("rerank_score"))
        loc = r.get("location") or {}
        loc_label = loc.get("page_label") or loc.get("timestamp_label") or "—"
        if summary["top_confidence"] is None:
            summary["top_confidence"] = r.get("confidence")
        print(f"  [{dom:5s}] {name:40s} conf={conf} dense={dense} lex={lex} "
              f"asf={asf} rer={rer}  loc={loc_label}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="검색 자동 검증")
    parser.add_argument("--queries", help="쿼리 JSON 파일 (리스트 또는 객체)")
    parser.add_argument("--top-k", type=int, default=5, help="결과 표시 개수")
    parser.add_argument("--type", default="", help="도메인 필터 (doc/image/video/audio)")
    parser.add_argument("--json", help="결과 JSON 저장 경로")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    queries = DEFAULT_QUERIES
    if args.queries:
        with open(args.queries, encoding="utf-8") as f:
            data = json.load(f)
        queries = data if isinstance(data, list) else data.get("queries", [])

    print(f"=== 검색 자동 검증 ({len(queries)} queries, top-{args.top_k}) ===")
    print(f"  API: {API_BASE}")
    if args.type:
        print(f"  type filter: {args.type}")

    summaries = []
    for i, q in enumerate(queries, 1):
        elapsed, data, err = fetch_search(q, top_k=args.top_k,
                                           type_filter=args.type,
                                           timeout=args.timeout)
        summaries.append(print_result(q, i, len(queries), elapsed, data, err, args.top_k))

    # 종합 통계
    print("\n" + "=" * 80)
    print("종합")
    print("=" * 80)
    ok_count = sum(1 for s in summaries if s["ok"])
    total_results = sum(s["result_count"] for s in summaries)
    avg_elapsed = sum(s["elapsed_sec"] for s in summaries) / max(len(summaries), 1)
    domain_total: dict = {}
    for s in summaries:
        for d, c in s["domains"].items():
            domain_total[d] = domain_total.get(d, 0) + c
    confs = [s["top_confidence"] for s in summaries if s["top_confidence"] is not None]
    avg_conf = (sum(confs) / len(confs)) if confs else 0

    print(f"  성공: {ok_count}/{len(summaries)}")
    print(f"  평균 응답: {avg_elapsed:.2f}s")
    print(f"  총 결과: {total_results}")
    print(f"  도메인 분포: {dict(sorted(domain_total.items(), key=lambda x: -x[1]))}")
    print(f"  평균 top-1 confidence: {avg_conf:.3f}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({
                "summaries": summaries,
                "stats": {
                    "ok": ok_count,
                    "total": len(summaries),
                    "avg_elapsed": avg_elapsed,
                    "domain_total": domain_total,
                    "avg_top_confidence": avg_conf,
                },
            }, f, ensure_ascii=False, indent=2)
        print(f"\nJSON 저장: {args.json}")

    return 0 if ok_count == len(summaries) else 1


if __name__ == "__main__":
    sys.exit(main())
