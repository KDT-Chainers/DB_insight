"""A + E 통합: 응답 시간 벤치마크 + 다양성 평가.

5 도메인 × 12 쿼리 (한/영/특수문자/긴쿼리/짧은쿼리 mix).
각 쿼리당 cold + warm 측정.

출력:
  logs/bench_perf.json   — 도메인×쿼리 별 latency (cold/warm) + 결과수 + top conf
  logs/bench_perf.txt    — 사람 읽기용 요약
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

os.environ["FORCE_CPU"] = "1"
os.environ["OMC_DISABLE_QWEN_PREWARM"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


QUERIES = {
    "doc_page": [
        "취업 통계", "예산", "AI 데이터센터", "OECD 교육",
        "건강보험", "research methodology", "보고서", "정책 분석",
        "Korean 한국어 mixed", "@#$ 특수문자!", "에",
        "한국과 일본의 교육 정책 비교 분석 보고서 (2024년 기준)",
    ],
    "image": [
        "잔잔한 풍경", "고양이", "사람 회의", "운전면허증",
        "주민등록증", "노트북", "음식 사진",
        "blue sky landscape", "documents on a table",
        "흐릿한 야외 사진", "pattern_05", "여행 풍경",
    ],
    "movie": [
        "회의 발표", "뉴스 보도", "AI 기술", "정치 이슈",
        "education policy", "취업 시장",
        "안녕하세요", "오늘은 어떤 일이 있었나요",
        "youtube 영상", "MBC", "라이브",
        "부동산 정책에 대한 분석 동영상 매우 긴 쿼리 테스트",
    ],
    "music": [
        "안녕하세요", "오늘 날씨", "음악", "lecture",
        "강의", "팟캐스트",
        "라디오 방송 김어준",
        "정치", "투자 조언",
        "Hello world test",
        "ㅎㅎ",
        "맛집 추천 영상 분석 강의 라이브 방송 콘텐츠",
    ],
    "bgm": [
        "잔잔한 피아노", "신나는 댄스 음악",
        "슬픈 발라드", "classical orchestra",
        "fast tempo electronic",
        "어두운 분위기",
        "밝고 경쾌한 음악",
        "기악곡",
        "vocal heavy",
        "instrumental",
        "BGM",
        "ambient mood relaxing",
    ],
}


def main():
    print("[bench] 엔진 로드 (CPU mode)...", flush=True)
    t0 = time.time()
    from routes.trichef import _get_engine
    from services.bgm.search_engine import get_engine as get_bgm_engine
    engine = _get_engine()
    bgm = get_bgm_engine()
    load_time = time.time() - t0
    print(f"  엔진 로드: {load_time:.1f}s", flush=True)

    results: dict = {"engine_load_sec": round(load_time, 2), "domains": {}}

    for domain, queries in QUERIES.items():
        per_q: list = []
        print(f"\n=== {domain} ===", flush=True)

        # cold/warm 측정 위해 첫 쿼리는 1번, 이후는 2번씩 (warm 측정용)
        for i, q in enumerate(queries):
            measurements = []
            for run in range(2):
                t1 = time.time()
                try:
                    if domain == "bgm":
                        r = bgm.search(q, top_k=5)
                        n = len(r.get("results", []))
                        top_conf = r.get("results", [{}])[0].get("confidence") if n else None
                        seg_count = sum(len(it.get("segments", [])) for it in r.get("results", []))
                    elif domain in ("movie", "music"):
                        hits = engine.search_av(q, domain=domain, topk=5, top_segments=3)
                        n = len(hits)
                        top_conf = hits[0].confidence if n else None
                        seg_count = sum(len(h.segments) for h in hits)
                    else:
                        hits = engine.search(q, domain=domain, topk=5, use_lexical=True, use_asf=True, pool=200)
                        n = len(hits)
                        top_conf = hits[0].confidence if n else None
                        seg_count = 0
                    elapsed = time.time() - t1
                    measurements.append({"elapsed": round(elapsed * 1000, 1),  # ms
                                         "n": n, "top_conf": top_conf})
                except Exception as e:
                    elapsed = time.time() - t1
                    measurements.append({"elapsed": round(elapsed * 1000, 1),
                                         "n": 0, "error": str(e)[:120]})
            cold_ms = measurements[0]["elapsed"]
            warm_ms = measurements[1]["elapsed"]
            n_results = measurements[0].get("n", 0)
            top_conf = measurements[0].get("top_conf")
            err = measurements[0].get("error")
            print(f"  [{i+1:2d}] q={q[:30]:<30} n={n_results}  cold={cold_ms:>6.1f}ms warm={warm_ms:>6.1f}ms  conf={top_conf}",
                  flush=True)
            per_q.append({
                "query": q,
                "n": n_results,
                "cold_ms": cold_ms,
                "warm_ms": warm_ms,
                "top_conf": top_conf,
                **({"error": err} if err else {}),
            })

        # 통계
        warm_times = [r["warm_ms"] for r in per_q if r.get("warm_ms")]
        n_zero = sum(1 for r in per_q if r["n"] == 0)
        n_err = sum(1 for r in per_q if r.get("error"))
        results["domains"][domain] = {
            "n_queries":      len(queries),
            "n_zero_results": n_zero,
            "n_errors":       n_err,
            "avg_warm_ms":    round(sum(warm_times) / len(warm_times), 1) if warm_times else None,
            "min_warm_ms":    round(min(warm_times), 1) if warm_times else None,
            "max_warm_ms":    round(max(warm_times), 1) if warm_times else None,
            "queries":        per_q,
        }

    # 저장
    log_dir = ROOT / "logs"
    (log_dir / "bench_perf.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    txt = []
    txt.append("=== 검색 응답 시간 + 다양성 평가 ===")
    txt.append(f"엔진 로드: {results['engine_load_sec']}s")
    txt.append("")
    txt.append(f"{'domain':<10} {'queries':<8} {'avg_warm':<10} {'min':<8} {'max':<8} {'zero':<6} {'err':<5}")
    txt.append("-" * 60)
    for d, st in results["domains"].items():
        txt.append(
            f"{d:<10} {st['n_queries']:<8} "
            f"{st['avg_warm_ms']:<10} "
            f"{st['min_warm_ms']:<8} "
            f"{st['max_warm_ms']:<8} "
            f"{st['n_zero_results']:<6} "
            f"{st['n_errors']:<5}"
        )
    (log_dir / "bench_perf.txt").write_text("\n".join(txt), encoding="utf-8")
    print()
    print("\n".join(txt), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
