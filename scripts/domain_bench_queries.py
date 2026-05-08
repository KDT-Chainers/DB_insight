"""scripts/domain_bench_queries.py — 5도메인 가상 쿼리 성능 벤치마크.

각 도메인별 7개 쿼리(적합 5 + 부적합 2)로 Hit@1/3/5, 평균 confidence,
부적합 차단율을 측정. local_bench_all.py 패턴 기반, BGM 도메인 추가.

실행:
  python scripts/domain_bench_queries.py
  python scripts/domain_bench_queries.py --topk 10 --domains doc image
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

# ── 쿼리셋 정의 ──────────────────────────────────────────────────────────────
# (query, domain, expected_keywords, is_irrelevant)
#   expected_keywords: 적합 쿼리 — 결과 id/파일명에 포함 기대 키워드
#   is_irrelevant=True: 부적합 쿼리 — 결과가 없거나 confidence < 0.40 이어야 함

EVAL_SET: list[tuple[str, str, list[str], bool]] = [
    # ── Doc (문서) ─────────────────────────────────────────────────────────
    ("탄소중립 정책",                    "doc_page", ["탄소", "중립", "기후", "환경"], False),
    ("재정건전화법안 입법과제",           "doc_page", ["재정", "법안", "입법", "국회"], False),
    ("인공지능 교육 소프트웨어",          "doc_page", ["인공지능", "AI", "교육", "SW"],  False),
    ("GDP 성장률 그래프 통계",            "doc_page", ["GDP", "성장", "통계", "경제"],   False),
    ("AI 인공지능 규제 정책 방향",          "doc_page", ["AI", "인공지능", "규제", "정책"], False),
    ("오늘 저녁 메뉴 추천",               "doc_page", [],                                 True),
    ("강아지 훈련 방법",                  "doc_page", [],                                 True),

    # ── Image (이미지) ─────────────────────────────────────────────────────
    # expected_keywords: 실제 이미지 파일명 카테고리 기준
    # (영진_1차/person_05.jpg, sports_12.jpg, vehicle_03.jpg 등 파일명 패턴에서 추출)
    ("강아지 고양이 귀여운 반려동물",     "image",    ["dog", "cat", "animal"],               False),
    ("사람 인물 산책 야외 활동",          "image",    ["person", "sports"],                   False),
    ("자동차 차량 교통 도시",             "image",    ["vehicle", "real"],                    False),
    ("음식 요리 식사 커피",               "image",    ["food", "coffee"],                     False),
    ("꽃 자연 풍경 노을",                 "image",    ["flower", "nature", "sunset"],          False),
    ("인공지능 코드 알고리즘 수식",       "image",    [],                                      True),
    ("법률 계약서 조항 문장",             "image",    [],                                      True),

    # ── Movie (영상) ───────────────────────────────────────────────────────
    ("코스모스",                          "movie",    ["코스모스", "cosmos"],                 False),
    ("인공지능의 미래 강연",              "movie",    ["AI", "인공지능", "미래", "강연"],      False),
    ("박태웅 의장",                       "movie",    ["박태웅", "의장"],                      False),
    ("우주 천문 다큐",                    "movie",    ["코스모스", "우주", "다큐"],             False),
    ("AI SaaS 창업 발표",                 "movie",    ["AI", "창업", "SaaS"],                  False),
    ("피자 만드는 방법 요리",             "movie",    [],                                       True),
    ("주식 투자 전략 분석",               "movie",    [],                                       True),

    # ── Rec (녹음/음성) ────────────────────────────────────────────────────
    ("머신러닝 기초 강의",                "music",    ["머신러닝", "ML", "machine", "학습"],   False),
    ("공부 방법 학생 상담",               "music",    ["공부", "학생", "상담"],                 False),
    ("Discord 봇 개발",                   "music",    ["Discord", "봇", "bot"],                False),
    ("AI 창업 SaaS 발표",                 "music",    ["AI", "창업", "SaaS"],                   False),
    ("고양이 동물 관련",                  "music",    ["고양이", "동물"],                        False),
    ("바나나 스무디 레시피",              "music",    [],                                        True),
    ("축구 경기 결과",                    "music",    [],                                        True),

    # ── BGM (배경음악) ─────────────────────────────────────────────────────
    ("잔잔한 피아노 배경음악",            "bgm",      ["piano", "calm", "relax"],               False),
    ("업템포 팝 광고음악",                "bgm",      ["pop", "upbeat", "ad"],                  False),
    ("어쿠스틱 기타 연주",                "bgm",      ["guitar", "acoustic"],                   False),
    ("슬프고 우울한 분위기",              "bgm",      ["sad", "melancholy", "slow"],             False),
    ("신나는 전자 음악 EDM",              "bgm",      ["edm", "electronic", "dance"],            False),
    ("오늘 점심 뭐 먹을까",               "bgm",      [],                                        True),
    ("자동차 엔진 수리 방법",             "bgm",      [],                                        True),
]

TOPK = 5


def _hit(id_str: str, kws: list[str]) -> bool:
    low = id_str.lower()
    return any(k.lower() in low for k in kws)


def search_domain(eng, bgm_eng, query: str, domain: str, topk: int) -> list[dict]:
    """도메인별 검색 실행, 결과 dict 리스트 반환."""
    results: list[dict] = []
    try:
        if domain == "bgm":
            if bgm_eng is None:
                return []
            raw = bgm_eng.search(query, topk=topk)
            for r in raw:
                results.append({
                    "id":         r.get("file_path", r.get("id", "")),
                    "score":      round(float(r.get("score", r.get("similarity", 0))), 4),
                    "confidence": round(float(r.get("confidence", 0)), 4),
                    "domain":     "bgm",
                })
        elif domain in ("movie", "music"):
            raw = eng.search_av(query, domain=domain, topk=topk)
            for r in raw:
                results.append({
                    "id":         r.file_path,
                    "score":      round(r.score, 4),
                    "confidence": round(r.confidence, 4),
                    "domain":     domain,
                })
        else:
            raw = eng.search(query, domain=domain, topk=topk, use_lexical=True)
            for r in raw:
                results.append({
                    "id":         r.id,
                    "score":      round(r.score, 4),
                    "confidence": round(r.confidence, 4),
                    "domain":     domain,
                })
    except Exception as e:
        results.append({"error": str(e)[:200]})
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topk", type=int, default=TOPK)
    parser.add_argument("--domains", nargs="*",
                        default=["doc_page", "image", "movie", "music", "bgm"],
                        help="점검할 도메인 목록")
    args = parser.parse_args()

    active_domains = set(args.domains)

    print("=" * 70)
    print("  DB_insight 도메인별 가상 쿼리 벤치마크")
    print(f"  topk={args.topk}  domains={sorted(active_domains)}")
    print("=" * 70)

    # 엔진 로드
    from services.trichef.unified_engine import TriChefEngine
    print("\n[엔진 로드 중...]")
    eng = TriChefEngine()
    print(f"  Tri-CHEF 캐시: {list(eng._cache.keys())}")

    bgm_eng = None
    if "bgm" in active_domains:
        try:
            from services.bgm.search_engine import BGMSearchEngine
            bgm_eng = BGMSearchEngine()
            print("  BGM 엔진 로드 완료")
        except Exception as e:
            print(f"  ⚠ BGM 엔진 로드 실패: {e} — BGM 도메인 skip")

    report: dict = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "topk": args.topk,
        "per_query": [],
        "summary": {},
    }

    # 도메인별 집계
    dom_stats: dict[str, dict] = {}

    for query, domain, kws, is_irrel in EVAL_SET:
        if domain not in active_domains:
            continue

        # domain이 캐시에 없으면 skip (AV도 search_av 가능 여부 확인)
        if domain not in ("bgm",) and domain not in eng._cache:
            # AV 도메인은 movie/music 키로 확인
            if domain in ("movie", "music") and domain not in eng._cache:
                print(f"\n[skip] {domain} 캐시 없음: {query!r}")
                continue

        ds = dom_stats.setdefault(domain, {
            "rel_queries": 0,    # 적합 쿼리 수
            "irrel_queries": 0,  # 부적합 쿼리 수
            "hit1": 0, "hit3": 0, "hit5": 0,
            "conf_sum": 0.0, "conf_cnt": 0,
            "irrel_blocked": 0,  # confidence < 0.40 이거나 빈 결과
        })

        results = search_domain(eng, bgm_eng, query, domain, args.topk)
        returned = len([r for r in results if "error" not in r])
        top_conf = results[0].get("confidence", 0) if results and "error" not in results[0] else 0.0

        row: dict = {
            "query":       query,
            "domain":      domain,
            "irrelevant":  is_irrel,
            "kws":         kws,
            "returned":    returned,
            "top_conf":    round(top_conf, 4),
            "results":     [r for r in results[:3]],
        }

        if is_irrel:
            ds["irrel_queries"] += 1
            blocked = returned == 0 or top_conf < 0.40
            row["blocked"] = blocked
            if blocked:
                ds["irrel_blocked"] += 1
            status = "✓차단" if blocked else "✗노출"
            print(f"\n  [부적합/{domain}] {status}  conf={top_conf:.3f}  '{query}'")
            if not blocked and results:
                print(f"    ⚠ 상위 결과: {results[0].get('id','')[:60]}")
        else:
            ds["rel_queries"] += 1
            hit_ids = [r.get("id", "") for r in results if "error" not in r]
            h1 = any(_hit(i, kws) for i in hit_ids[:1])
            h3 = any(_hit(i, kws) for i in hit_ids[:3])
            h5 = any(_hit(i, kws) for i in hit_ids[:5])
            if h1: ds["hit1"] += 1
            if h3: ds["hit3"] += 1
            if h5: ds["hit5"] += 1
            if top_conf > 0:
                ds["conf_sum"] += top_conf
                ds["conf_cnt"] += 1

            row["hit1"] = h1; row["hit3"] = h3; row["hit5"] = h5

            mark1 = "✓" if h1 else ("△" if h3 else ("▽" if h5 else "✗"))
            print(f"\n  [{domain}] {mark1} H@1={int(h1)} H@3={int(h3)} H@5={int(h5)}"
                  f"  conf={top_conf:.3f}  '{query}'")
            for r in results[:2]:
                flag = "*" if _hit(r.get("id", ""), kws) else " "
                print(f"    {flag} s={r.get('score',0):.3f} c={r.get('confidence',0):.3f}"
                      f"  {r.get('id','')[:60]}")

        report["per_query"].append(row)

    # 요약 계산
    print(f"\n{'=' * 70}")
    print(f"{'도메인':<12} {'H@1':>6} {'H@3':>6} {'H@5':>6} {'AvgConf':>8} {'부적합차단':>10}")
    print("-" * 70)

    for domain, ds in sorted(dom_stats.items()):
        rn = max(ds["rel_queries"], 1)
        irn = max(ds["irrel_queries"], 1)
        h1 = ds["hit1"] / rn
        h3 = ds["hit3"] / rn
        h5 = ds["hit5"] / rn
        avg_conf = ds["conf_sum"] / max(ds["conf_cnt"], 1)
        block_rate = ds["irrel_blocked"] / irn

        report["summary"][domain] = {
            "rel_queries": ds["rel_queries"],
            "irrel_queries": ds["irrel_queries"],
            "hit_at_1": round(h1, 3),
            "hit_at_3": round(h3, 3),
            "hit_at_5": round(h5, 3),
            "avg_top_confidence": round(avg_conf, 3),
            "irrelevant_block_rate": round(block_rate, 3),
        }
        print(f"{domain:<12} {h1:>6.1%} {h3:>6.1%} {h5:>6.1%} "
              f"{avg_conf:>8.3f} {block_rate:>10.1%}")

    out_dir = ROOT / "bench_results"
    out_dir.mkdir(exist_ok=True)
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"{ts}_domain_bench_queries.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[saved] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
