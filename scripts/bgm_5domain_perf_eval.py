"""5도메인 종합 검색 성능 평가 — 품질 + 응답시간 + 통합 confidence.

각 도메인 15개 쿼리:
  - 강한 매칭 (관련성 명확) 5개
  - 약한 매칭 (모호) 5개
  - 무관/edge case 5개

지표:
  - 응답 시간 p50/p95
  - confidence 분포 (>90% / 70~90% / 50~70% / <50%)
  - top-1 relevant 추정 (heuristic — 사용자 검토용 raw 결과 출력)
  - 도메인 간 confidence 분포 일관성
"""
from __future__ import annotations
import json, os, sys, time
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
    "doc_page": {
        "강한매칭":  ["취업 통계 보고서", "AI 데이터센터", "건강보험 제도", "예산 정책 분석", "OECD 교육 통계"],
        "약한매칭":  ["관련 자료 요약", "최근 자료", "근로자", "대학", "문제점 분석"],
        "edge":     ["", "@#$%^", "ㅎ", "lorem ipsum", "1234"],
    },
    "image": {
        "강한매칭":  ["고양이", "산 풍경", "사람 회의", "운전면허증", "노트북"],
        "약한매칭":  ["야외 사진", "실내 모임", "텍스트 문서", "여행", "음식"],
        "edge":     ["", "🐱", "...", "abc", "지하"],
    },
    "movie": {
        "강한매칭":  ["AI 기술 소개", "정치 이슈 토론", "뉴스 보도 사건", "교육 콘텐츠", "경제 분석 영상"],
        "약한매칭":  ["분석", "강의", "토론", "라이브", "리포트"],
        "edge":     ["", "ㅋㅋ", "test 1234", "abc", "@@@@"],
    },
    "music": {
        "강한매칭":  ["라디오 방송", "정치 강의", "투자 전략 설명", "팟캐스트 인터뷰", "토론 프로그램"],
        "약한매칭":  ["강의", "안녕하세요", "오늘", "분석", "저는"],
        "edge":     ["", "ㅎㅎ", "test", "abc", "🎵"],
    },
    "bgm": {
        "강한매칭":  ["잔잔한 피아노", "신나는 댄스 음악", "classical orchestra", "어두운 분위기 BGM", "fast tempo electronic"],
        "약한매칭":  ["음악", "BGM", "배경음악", "instrumental", "vocal"],
        "edge":     ["", "ㅎㅎ", "1234", "abc", "🎵🎶"],
    },
}


def main():
    print("=== 5도메인 종합 검색 성능 평가 ===")
    print(f"[load] 엔진 로드 (CPU mode)...", flush=True)
    t0 = time.time()
    from routes.trichef import _get_engine
    from services.bgm.search_engine import get_engine as get_bgm
    engine = _get_engine()
    bgm = get_bgm()
    print(f"[load] 완료 ({time.time()-t0:.1f}s)\n", flush=True)

    results: dict = {"meta": {"engine_load_sec": round(time.time()-t0, 2)},
                     "domains": {}}
    detail_text: list[str] = []

    for domain, groups in QUERIES.items():
        print(f"\n=== [{domain}] ===", flush=True)
        domain_stats = {
            "n_queries":   0,
            "errors":      0,
            "zero_result": 0,
            "high_conf":   0,   # >90%
            "med_conf":    0,   # 70~90%
            "weak_conf":   0,   # 50~70%
            "low_conf":    0,   # <50%
            "latencies":   [],  # warm latencies (ms)
            "groups":      {},
        }
        detail_text.append(f"\n=== [{domain}] ===")

        for grp_name, queries in groups.items():
            grp_lat = []
            grp_results = []
            detail_text.append(f"\n  -- {grp_name} --")
            for q in queries:
                # cold + warm
                latencies = []
                top_results = []
                for run in range(2):
                    t = time.time()
                    try:
                        if domain == "bgm":
                            r = bgm.search(q, top_k=5)
                            items = r.get("results", [])
                            top1_conf = items[0]["confidence"] if items else None
                            top1_name = items[0].get("filename", "") if items else ""
                            n = len(items)
                        elif domain in ("movie", "music"):
                            hits = engine.search_av(q, domain=domain, topk=5)
                            top1_conf = hits[0].confidence if hits else None
                            top1_name = hits[0].file_name[:50] if hits else ""
                            n = len(hits)
                        else:
                            hits = engine.search(q, domain=domain, topk=5,
                                                 use_lexical=True, use_asf=True)
                            top1_conf = hits[0].confidence if hits else None
                            top1_name = hits[0].id[:60] if hits else ""
                            n = len(hits)
                        latencies.append((time.time() - t) * 1000)
                        top_results.append({"n": n, "conf": top1_conf, "name": top1_name})
                    except Exception as ex:
                        latencies.append(-1)
                        top_results.append({"error": str(ex)[:100]})

                # 통계 (warm 사용)
                warm = top_results[1] if len(top_results) > 1 else top_results[0]
                warm_lat = latencies[1] if len(latencies) > 1 else latencies[0]

                domain_stats["n_queries"] += 1
                if warm.get("error"):
                    domain_stats["errors"] += 1
                elif warm.get("n", 0) == 0:
                    domain_stats["zero_result"] += 1

                conf = warm.get("conf")
                if conf is not None:
                    if conf >= 0.90:    domain_stats["high_conf"] += 1
                    elif conf >= 0.70:  domain_stats["med_conf"]  += 1
                    elif conf >= 0.50:  domain_stats["weak_conf"] += 1
                    else:               domain_stats["low_conf"]  += 1

                if warm_lat > 0:
                    domain_stats["latencies"].append(warm_lat)
                    grp_lat.append(warm_lat)
                grp_results.append({"q": q, "warm": warm, "warm_lat": warm_lat})

                # 출력 + detail
                conf_str = f"{conf*100:.0f}%" if conf is not None else "—"
                print(f"  {grp_name[:4]:>4} q={q[:20]!r:<22} n={warm.get('n',0)} conf={conf_str:<5} ({warm_lat:>5.0f}ms)",
                      flush=True)
                detail_text.append(
                    f"  {grp_name[:4]:>4} q={q!r:<25} top1={warm.get('name','')[:55]:<55} "
                    f"conf={conf_str:>5} ({warm_lat:.0f}ms)"
                )
            domain_stats["groups"][grp_name] = grp_results

        # 도메인 통계
        lats = domain_stats["latencies"]
        lats.sort()
        n = len(lats)
        if n > 0:
            domain_stats["lat_p50"] = round(lats[n // 2], 1)
            domain_stats["lat_p95"] = round(lats[int(n * 0.95)], 1) if n > 1 else lats[0]
            domain_stats["lat_avg"] = round(sum(lats) / n, 1)
        else:
            domain_stats["lat_p50"] = domain_stats["lat_p95"] = domain_stats["lat_avg"] = None

        results["domains"][domain] = domain_stats
        print(f"  >> {domain}: high={domain_stats['high_conf']}, med={domain_stats['med_conf']}, "
              f"weak={domain_stats['weak_conf']}, low={domain_stats['low_conf']}, "
              f"p50={domain_stats['lat_p50']}ms p95={domain_stats['lat_p95']}ms",
              flush=True)

    # 종합 출력
    print()
    print("=" * 80, flush=True)
    print("종합 요약 (15개 쿼리 × 5도메인 = 75 쿼리)", flush=True)
    print("=" * 80, flush=True)
    print(f"{'도메인':<10} {'queries':<8} {'errors':<7} {'zero':<6} {'>90%':<6} {'70-90%':<7} {'50-70%':<7} {'<50%':<6} {'p50':<7} {'p95':<7}",
          flush=True)
    print("-" * 80, flush=True)
    for d, st in results["domains"].items():
        print(f"{d:<10} {st['n_queries']:<8} {st['errors']:<7} {st['zero_result']:<6} "
              f"{st['high_conf']:<6} {st['med_conf']:<7} {st['weak_conf']:<7} {st['low_conf']:<6} "
              f"{st['lat_p50']:<7} {st['lat_p95']:<7}", flush=True)

    # 저장
    log_dir = ROOT / "logs"
    (log_dir / "bench_5domain.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (log_dir / "bench_5domain.txt").write_text(
        "\n".join(detail_text), encoding="utf-8"
    )
    print(f"\n저장: logs/bench_5domain.json + .txt", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
