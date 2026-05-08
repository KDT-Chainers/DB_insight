"""scripts/test_irrelevant_queries.py — 부적합 쿼리 필터링 강도 점검.

완전히 무관한 쿼리(음식, 스포츠 등)가 각 도메인에서 confidence < 0.40 으로
필터링되는지 검증. fallback 메커니즘이 무관 결과를 노출하는지도 확인.

실행:
  python scripts/test_irrelevant_queries.py
  python scripts/test_irrelevant_queries.py --threshold 0.40
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

# 완전 무관 쿼리 — 어떤 도메인 데이터와도 관련 없어야 함
IRRELEVANT_QUERIES: list[str] = [
    "오늘 저녁 파스타 레시피",
    "강아지 미용 방법",
    "주식 투자 종목 추천",
    "자동차 엔진 오일 교환",
    "바나나 케이크 만들기",
    "축구 경기 결과 분석",
    "수학 미분 공식 풀이",
    "캠핑 텐트 설치 방법",
    "고혈압 약 복용 방법",
    "화분 물주기 주기",
]

# 도메인별 검증 (search_av는 별도 처리)
DOMAINS_TEXT = ["doc_page", "image"]
DOMAINS_AV   = ["movie", "music"]
DOMAINS_BGM  = ["bgm"]

CONF_THRESHOLD = 0.40   # CMP 무관 판별 임계값


def _check_blocked(results: list, threshold: float) -> tuple[bool, float]:
    """결과가 threshold 미만으로 차단됐는지 여부와 top confidence 반환."""
    if not results:
        return True, 0.0
    top_conf = max(float(r.get("confidence", 0)) for r in results if "error" not in r)
    return top_conf < threshold, top_conf


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=CONF_THRESHOLD)
    args = parser.parse_args()
    thr = args.threshold

    print("=" * 65)
    print(f"  부적합 쿼리 필터링 점검  (threshold={thr})")
    print("=" * 65)

    from services.trichef.unified_engine import TriChefEngine
    print("\n[엔진 로드 중...]")
    eng = TriChefEngine()
    active = set(eng._cache.keys())

    bgm_eng = None
    try:
        from services.bgm.search_engine import BGMSearchEngine
        bgm_eng = BGMSearchEngine()
    except Exception:
        pass

    report: dict = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "threshold": thr,
        "per_domain": {},
        "per_query": [],
        "summary": {},
    }

    all_domains = (
        [d for d in DOMAINS_TEXT if d in active] +
        [d for d in DOMAINS_AV   if d in active] +
        (DOMAINS_BGM if bgm_eng else [])
    )

    dom_stats: dict[str, dict] = {
        d: {"blocked": 0, "exposed": 0, "conf_sum": 0.0} for d in all_domains
    }

    for query in IRRELEVANT_QUERIES:
        print(f"\n쿼리: '{query}'")
        row: dict = {"query": query, "domains": {}}

        for domain in all_domains:
            try:
                if domain == "bgm":
                    raw = bgm_eng.search(query, topk=5)
                    results = [
                        {"id": r.get("file_path", ""), "confidence": float(r.get("confidence", 0))}
                        for r in raw
                    ]
                elif domain in ("movie", "music"):
                    raw = eng.search_av(query, domain=domain, topk=5)
                    results = [
                        {"id": r.file_path, "confidence": float(r.confidence)}
                        for r in raw
                    ]
                else:
                    raw = eng.search(query, domain=domain, topk=5, use_lexical=True)
                    results = [
                        {"id": r.id, "confidence": float(r.confidence),
                         "fallback": r.metadata.get("fallback", False)}
                        for r in raw
                    ]
            except Exception as e:
                results = [{"error": str(e)[:100]}]

            blocked, top_conf = _check_blocked(results, thr)
            is_fallback = any(r.get("fallback") for r in results if "error" not in r)

            dom_stats[domain]["conf_sum"] += top_conf
            if blocked:
                dom_stats[domain]["blocked"] += 1
                status = "✓차단"
            else:
                dom_stats[domain]["exposed"] += 1
                status = "✗노출"

            fb_tag = " [fallback]" if is_fallback else ""
            print(f"  {domain:<12} {status}{fb_tag}  conf={top_conf:.3f}", end="")
            if not blocked and results:
                print(f"  → {results[0].get('id','')[:45]}", end="")
            print()

            row["domains"][domain] = {
                "blocked": blocked,
                "top_conf": round(top_conf, 4),
                "fallback": is_fallback,
                "top_result": results[0].get("id", "") if results and "error" not in results[0] else "",
            }

        report["per_query"].append(row)

    # 도메인별 요약
    n_queries = len(IRRELEVANT_QUERIES)
    print(f"\n{'=' * 65}")
    print(f"{'도메인':<14} {'차단률':>8}  {'평균conf':>8}  {'fallback위험':>12}")
    print("-" * 65)

    for domain in all_domains:
        s = dom_stats[domain]
        block_rate = s["blocked"] / n_queries
        avg_conf   = s["conf_sum"] / n_queries
        # fallback 노출 수
        fb_exposed = sum(
            1 for row in report["per_query"]
            if row["domains"].get(domain, {}).get("fallback")
               and not row["domains"][domain].get("blocked")
        )

        status = "✓" if block_rate >= 0.80 else ("⚠" if block_rate >= 0.50 else "✗")
        print(f"  [{status}] {domain:<12} {block_rate:>7.1%}  {avg_conf:>8.3f}  {fb_exposed:>8}건")

        report["per_domain"][domain] = {
            "block_rate":    round(block_rate, 3),
            "avg_conf":      round(avg_conf, 3),
            "blocked":       s["blocked"],
            "exposed":       s["exposed"],
            "fallback_exposed": fb_exposed,
        }
        report["summary"][domain] = report["per_domain"][domain]

    # 전체 요약
    overall_blocked = sum(s["blocked"] for s in dom_stats.values())
    overall_total   = n_queries * len(all_domains)
    overall_rate    = overall_blocked / max(overall_total, 1)

    print(f"\n  전체 차단률: {overall_rate:.1%}  ({overall_blocked}/{overall_total})")
    if overall_rate < 0.70:
        print("  ⚠ 전체 차단률 70% 미만 — 임계값/캘리브레이션 재검토 권장")

    # fallback 노출 도메인 경고
    fallback_doms = [
        d for d in all_domains
        if report["per_domain"][d]["fallback_exposed"] > 0
    ]
    if fallback_doms:
        print(f"\n  ⚠ fallback 노출 도메인: {fallback_doms}")
        print("    → abs_threshold 통과 결과 없어도 top-K fallback 반환 중")
        print("    → unified_engine.py 의 fallback 조건 강화 검토 필요")

    out_dir = ROOT / "bench_results"
    out_dir.mkdir(exist_ok=True)
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"{ts}_test_irrelevant_queries.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[saved] {out}")
    return 0 if overall_rate >= 0.80 else 1


if __name__ == "__main__":
    sys.exit(main())
