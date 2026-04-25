"""scripts/local_bench_v2.py — 듀얼 메트릭 벤치 v2.

두 gold 산출 방식을 병행 평가:
  (A) filename-kw  : 기존 방식 호환 (회귀 비교용)
  (B) content-aware: gold = 쿼리와 caption/STT 텍스트의 BGE-M3 코사인 ≥ θ

출력:
  bench_results/{ts}_local_bench_v2.json
  콘솔 표: 도메인 × config × {fn_metric, ct_metric}

공통 라이브러리: scripts/_bench_common.py
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(ROOT / "App" / "backend")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from services.trichef.unified_engine import TriChefEngine  # noqa: E402
from _bench_common import (  # noqa: E402
    ContentGoldDB,
    CONTENT_THETA,
    _ensure_encoder,
    _precision_at_k,
)
import _bench_common as _bc

# ── 쿼리 셋 (도메인별 ≥ 10개) ──────────────────────────────────────────────
# (쿼리, 도메인, 기대 키워드 리스트)
EVAL_SET: list[tuple[str, str, list[str]]] = [
    # ── image (2 → 12) ──────────────────────────────────────────────────────
    ("산과 자연",       "image", ["산", "자연", "풍경", "mountain", "nature"]),
    ("도시 야경",       "image", ["도시", "야경", "city", "night", "urban"]),
    ("음식 사진",       "image", ["음식", "식사", "food", "meal", "요리"]),
    ("동물 일상",       "image", ["동물", "animal", "pet", "고양이", "강아지"]),
    ("여행 풍경",       "image", ["여행", "travel", "풍경", "landscape", "관광"]),
    ("장난감 자동차",   "image", ["자동차", "car", "장난감", "toy", "vehicle"]),
    ("노을 그림",       "image", ["노을", "sunset", "하늘", "sky", "evening"]),
    ("사람 단체사진",   "image", ["사람", "face", "portrait", "person", "group"]),
    ("실내 인테리어",   "image", ["실내", "인테리어", "indoor", "room", "interior"]),
    ("꽃 클로즈업",     "image", ["꽃", "flower", "close", "bloom", "식물"]),
    ("스포츠 활동",     "image", ["스포츠", "sport", "활동", "운동", "outdoor"]),
    ("겨울 눈 풍경",    "image", ["겨울", "눈", "snow", "winter", "frost"]),
    # ── doc_page (5 → 10) ────────────────────────────────────────────────────
    ("환경 정책",       "doc_page", ["환경", "정책", "기후", "탄소", "그린"]),
    ("인공지능 교육",   "doc_page", ["인공지능", "AI", "교육", "SW", "소프트웨어"]),
    ("탄소중립",        "doc_page", ["탄소", "중립", "기후", "환경", "ESG"]),
    ("디지털 전환",     "doc_page", ["디지털", "전환", "DX", "SW", "ICT"]),
    ("반도체 산업",     "doc_page", ["반도체", "산업", "Samsung", "하이닉스"]),
    ("AI 기술 동향",    "doc_page", ["AI", "인공지능", "기술", "LLM", "머신러닝"]),
    ("교육 정책",       "doc_page", ["교육", "정책", "학교", "학생", "커리큘럼"]),
    ("스마트시티",      "doc_page", ["스마트시티", "도시", "IoT", "스마트", "인프라"]),
    ("메타버스",        "doc_page", ["메타버스", "VR", "AR", "가상현실", "metaverse"]),
    ("데이터 거버넌스", "doc_page", ["데이터", "거버넌스", "개인정보", "보안", "규제"]),
    # ── movie (8 → 10) ───────────────────────────────────────────────────────
    ("게임 플레이",     "movie", ["게임", "플레이", "BGM"]),
    ("뉴스 보도",       "movie", ["뉴스", "JTBC", "SBS", "MBC"]),
    ("AI 창업",         "movie", ["AI", "창업", "SaaS", "LLM"]),
    ("우주 천문",       "movie", ["코스모스", "우주", "인간과 우주", "다큐"]),
    ("외계 생명체",     "movie", ["외계인", "코스모스", "우주"]),
    ("인간의 기원",     "movie", ["원시인", "기원", "인간과 우주"]),
    ("실크로드 문명",   "movie", ["실크로드", "西安", "서역", "사막"]),
    ("고대 제국",       "movie", ["제국", "전사", "고선지", "고구려"]),
    ("다큐멘터리 자연", "movie", ["자연", "nature", "다큐", "동물", "생태"]),
    ("역사 이야기",     "movie", ["역사", "조선", "고려", "고대", "문명"]),
    # ── music (5 → 10) ───────────────────────────────────────────────────────
    ("공부 방법",       "music", ["공부", "학생", "교육"]),
    ("학생 상담",       "music", ["상담", "면담", "선생님", "민호", "서연"]),
    ("AI SaaS 창업",    "music", ["AI", "창업", "SaaS"]),
    ("Discord 봇",      "music", ["Discord", "봇", "bot"]),
    ("고양이",          "music", ["고양이", "동물", "이사"]),
    ("동물 사연",       "music", ["동물", "사연", "고양이", "강아지", "반려"]),
    ("취미 활동",       "music", ["취미", "활동", "운동", "여가", "hobby"]),
    ("감성 토크",       "music", ["감성", "토크", "이야기", "감정", "대화"]),
    ("Q&A 세션",        "music", ["질문", "답변", "Q&A", "세션", "퀘스천"]),
    ("음악 감상",       "music", ["음악", "감상", "노래", "멜로디", "music"]),
]

TOPK = 5

CONFIGS = [
    ("dense",        {"use_lexical": False, "use_asf": False}),
    ("dense+sparse", {"use_lexical": True,  "use_asf": False}),
    ("dense+sp+asf", {"use_lexical": True,  "use_asf": True}),
]


# ── filename-kw 히트 ─────────────────────────────────────────────────────────
def _hit(id_str: str, kws: list[str]) -> bool:
    low = id_str.lower()
    return any(k.lower() in low for k in kws)


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[local_bench_v2] ROOT={ROOT}")
    print(f"[local_bench_v2] EVAL_SET: {len(EVAL_SET)} queries")

    eng = TriChefEngine()
    print(f"[local_bench_v2] cache domains: {list(eng._cache.keys())}")

    print("[local_bench_v2] content-aware gold DB 구축 중...")
    gold_db = ContentGoldDB()

    ts_iso = datetime.datetime.now().isoformat(timespec="seconds")
    report: dict = {
        "timestamp": ts_iso,
        "topk": TOPK,
        "configs": [c for c, _ in CONFIGS],
        "content_theta": CONTENT_THETA,
        "encoder_ok": _bc._bgem3_ok,
        "per_query": [],
        "summary_by_domain": {},
        "summary_overall": {},
    }

    # {cfg: {dom: {fn_hits, ct_hits, ct_total, fn_returned, ct_gold_queries}}}
    agg: dict[str, dict[str, dict]] = {
        n: {} for n, _ in CONFIGS
    }
    overall: dict[str, dict] = {
        n: {"fn_hits": 0, "fn_returned": 0,
            "ct_hits": 0, "ct_returned": 0, "ct_gold_queries": 0}
        for n, _ in CONFIGS
    }

    for q, dom, kws in EVAL_SET:
        if dom not in eng._cache:
            print(f"\n=== {dom} | '{q}' === SKIP (캐시 없음)")
            continue

        # content gold (쿼리 1회만 계산)
        gold_set = gold_db.gold_ids(q, dom)
        gold_size = len(gold_set) if gold_set is not None else None

        row = {
            "query": q, "domain": dom, "kws": kws,
            "gold_size": gold_size,
            "configs": {},
        }
        print(f"\n=== {dom} | {q!r}  [gold={gold_size if gold_size is not None else 'N/A'}] ===")

        for cfg_name, flags in CONFIGS:
            try:
                results = eng.search(q, domain=dom, topk=TOPK, **flags)
            except Exception as e:
                print(f"  [{cfg_name:14s}] ERROR: {e}")
                row["configs"][cfg_name] = {"error": str(e)[:200]}
                continue

            returned = len(results)

            # (A) filename-kw metric
            fn_hits = sum(1 for h in results if _hit(h.id, kws))

            # (B) content-aware metric
            ct_p5: Optional[float] = None
            ct_hits_val = None
            if gold_set is not None:
                if gold_size == 0:
                    ct_p5 = None  # gold 없음 → skip
                else:
                    ct_hits_val = sum(1 for h in results if h.id in gold_set)
                    ct_p5 = round(ct_hits_val / max(returned, 1), 4)

            row["configs"][cfg_name] = {
                "returned":  returned,
                "fn_hits":   fn_hits,
                "fn_p5":     round(fn_hits / max(returned, 1), 4),
                "ct_hits":   ct_hits_val,
                "ct_p5":     ct_p5,
                "gold_size": gold_size,
                "top": [{"id": h.id, "score": round(h.score, 4),
                          "conf": round(h.confidence, 4)} for h in results[:3]],
            }

            ct_str = f"{ct_p5:.4f}" if ct_p5 is not None else "N/A "
            print(f"  [{cfg_name:14s}] returned={returned}/{TOPK}"
                  f"  fn_hits={fn_hits}  fn_p5={fn_hits/max(returned,1):.3f}"
                  f"  ct_p5={ct_str}")
            for h in results[:3]:
                fn_mark = " F" if _hit(h.id, kws) else "  "
                ct_mark = "C" if (gold_set and h.id in gold_set) else " "
                print(f"    {fn_mark}{ct_mark} s={h.score:.3f} c={h.confidence:.3f}  {h.id[:65]}")

            # aggregate
            agg[cfg_name].setdefault(dom, {
                "fn_hits": 0, "fn_returned": 0,
                "ct_hits": 0, "ct_returned": 0, "ct_gold_queries": 0,
            })
            agg[cfg_name][dom]["fn_hits"]    += fn_hits
            agg[cfg_name][dom]["fn_returned"] += returned
            overall[cfg_name]["fn_hits"]    += fn_hits
            overall[cfg_name]["fn_returned"] += returned

            if ct_p5 is not None and ct_hits_val is not None:
                agg[cfg_name][dom]["ct_hits"]    += ct_hits_val
                agg[cfg_name][dom]["ct_returned"] += returned
                agg[cfg_name][dom]["ct_gold_queries"] += 1
                overall[cfg_name]["ct_hits"]    += ct_hits_val
                overall[cfg_name]["ct_returned"] += returned
                overall[cfg_name]["ct_gold_queries"] += 1

        report["per_query"].append(row)

    # ── per-query divergence 분석 ─────────────────────────────────────────────
    best_cfg = "dense+sp+asf"
    print("\n" + "=" * 80)
    print(f"[per-query divergence — {best_cfg}] fn ≠ ct (한 쪽만 1 이상)")
    print(f"  {'쿼리':<22} {'domain':<10} {'fn_p5':>6} {'ct_p5':>6}  {'gold':>5}")
    for pq in report["per_query"]:
        cfg_data = pq["configs"].get(best_cfg)
        if not cfg_data or "error" in cfg_data:
            continue
        fn_p5 = cfg_data.get("fn_p5", 0) or 0
        ct_p5 = cfg_data.get("ct_p5")
        if ct_p5 is None:
            continue
        if abs(fn_p5 - ct_p5) > 0.15:
            print(f"  {pq['query']:<22} {pq['domain']:<10} {fn_p5:>6.3f} {ct_p5:>6.3f}  {pq['gold_size'] or 0:>5}")

    # ── summary 계산 ─────────────────────────────────────────────────────────
    DOMAINS = ("image", "doc_page", "movie", "music")
    for cfg_name, _ in CONFIGS:
        dom_sum = {}
        for dom in DOMAINS:
            v = agg[cfg_name].get(dom)
            if not v:
                continue
            fn_r  = round(v["fn_hits"] / max(v["fn_returned"], 1), 3)
            ct_r  = round(v["ct_hits"] / max(v["ct_returned"], 1), 3) if v["ct_returned"] else None
            dom_sum[dom] = {
                "fn_rate": fn_r, "fn_hits": v["fn_hits"], "fn_returned": v["fn_returned"],
                "ct_rate": ct_r, "ct_hits": v["ct_hits"], "ct_returned": v["ct_returned"],
                "ct_gold_queries": v["ct_gold_queries"],
            }
        report["summary_by_domain"][cfg_name] = dom_sum

        o = overall[cfg_name]
        report["summary_overall"][cfg_name] = {
            "fn_rate": round(o["fn_hits"] / max(o["fn_returned"], 1), 3),
            "fn_hits": o["fn_hits"], "fn_returned": o["fn_returned"],
            "ct_rate": round(o["ct_hits"] / max(o["ct_returned"], 1), 3) if o["ct_returned"] else None,
            "ct_hits": o["ct_hits"], "ct_returned": o["ct_returned"],
            "ct_gold_queries": o["ct_gold_queries"],
        }

    # ── 콘솔 요약 표 ──────────────────────────────────────────────────────────
    print("\n" + "=" * 90)
    header = f"{'config':<16} {'overall_fn':>10} {'overall_ct':>10}  "
    for d in DOMAINS:
        header += f"{d+'_fn':>10} {d+'_ct':>10}  "
    print(header)
    print("-" * 90)

    for cfg_name, _ in CONFIGS:
        ov = report["summary_overall"][cfg_name]
        fn_str = f"{ov['fn_rate']:.3f}"
        ct_str = f"{ov['ct_rate']:.3f}" if ov["ct_rate"] is not None else " N/A"
        row_s = f"{cfg_name:<16} {fn_str:>10} {ct_str:>10}  "
        for d in DOMAINS:
            v = report["summary_by_domain"][cfg_name].get(d)
            if v:
                fn_d = f"{v['fn_rate']:.3f}"
                ct_d = f"{v['ct_rate']:.3f}" if v["ct_rate"] is not None else " N/A"
            else:
                fn_d = ct_d = "  --"
            row_s += f"{fn_d:>10} {ct_d:>10}  "
        print(row_s)

    # ── 저장 ─────────────────────────────────────────────────────────────────
    out_dir = ROOT / "bench_results"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"{ts}_local_bench_v2.json"
    # 저장 전 encoder_ok 갱신 (lazy 로드 후 상태 반영)
    report["encoder_ok"] = bool(_bc._bgem3_ok)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    main()
