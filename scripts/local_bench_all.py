"""scripts/local_bench_all.py — 4 도메인 전체 로컬 벤치 (서버 불필요).

TriChefEngine 직접 import — Flask/HTTP 없음. Phase 4 baseline 확보용.

평가 방식 (e2e_eval 확장판):
  각 쿼리에 대해 dense / dense+sparse / dense+sp+asf 3 구성 실행.
  proxy precision = top-K 결과 id/경로에 기대 키워드 중 하나라도 포함되는 비율.

결과: `bench_results/{timestamp}_local_bench_all.json`
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from services.trichef.unified_engine import TriChefEngine  # noqa: E402


# (쿼리, 도메인, 기대 키워드 리스트)
EVAL_SET: list[tuple[str, str, list[str]]] = [
    # ── doc_page (e2e_eval 기존 6개) ─────────────────────────
    ("환경 정책",      "doc_page", ["환경", "정책", "기후", "탄소", "그린"]),
    ("인공지능 교육",  "doc_page", ["인공지능", "AI", "교육", "SW", "소프트웨어"]),
    ("탄소중립",       "doc_page", ["탄소", "중립", "기후", "환경", "ESG"]),
    ("디지털 전환",    "doc_page", ["디지털", "전환", "DX", "SW", "ICT"]),
    ("반도체 산업",    "doc_page", ["반도체", "산업", "Samsung", "하이닉스"]),
    # ── image ────────────────────────────────────────────────
    ("사람 얼굴",      "image",    ["face", "portrait", "person", "IMG", "jpg", "JPG"]),
    ("풍경 사진",      "image",    ["landscape", "scene", "outdoor"]),
    # ── movie (MR_TriCHEF cached; registry 확인 시 콘텐츠 샘플 참고) ──
    ("게임 플레이",    "movie",    ["게임", "플레이", "BGM"]),
    ("뉴스 보도",      "movie",    ["뉴스", "JTBC", "SBS"]),
    ("AI 창업",        "movie",    ["AI", "창업", "SaaS", "LLM"]),
    # ── movie 다큐 (YS_다큐_1차) ─────────────────────────────────────
    ("우주 천문",      "movie",    ["코스모스", "우주", "인간과 우주", "다큐"]),
    ("외계 생명체",    "movie",    ["외계인", "코스모스", "우주"]),
    ("인간의 기원",    "movie",    ["원시인", "기원", "인간과 우주"]),
    # ── movie 다큐 (YS_다큐_2차 — 인덱싱 후 활성화) ──────────────────
    ("실크로드 문명",  "movie",    ["실크로드", "西安", "서역", "사막"]),
    ("고대 제국",      "movie",    ["제국", "전사", "고선지", "고구려"]),
    # ── music (bench_av.MUSIC_QUERIES + 기타) ────────────────
    ("공부 방법",      "music",    ["공부", "학생", "교육"]),
    ("학생 상담",      "music",    ["상담", "면담", "선생님", "민호", "서연"]),
    ("AI SaaS 창업",   "music",    ["AI", "창업", "SaaS"]),
    ("Discord 봇",     "music",    ["Discord", "봇", "bot"]),
    ("고양이",         "music",    ["고양이", "동물", "이사"]),
]

TOPK = 5
CONFIGS = [
    ("dense",         {"use_lexical": False, "use_asf": False}),
    ("dense+sparse",  {"use_lexical": True,  "use_asf": False}),
    ("dense+sp+asf",  {"use_lexical": True,  "use_asf": True}),
]


def _hit(id_str: str, kws: list[str]) -> bool:
    low = id_str.lower()
    return any(k.lower() in low for k in kws)


def main() -> None:
    print(f"[local_bench] ROOT={ROOT}")
    print(f"[local_bench] EVAL_SET: {len(EVAL_SET)} queries across 4 domains")
    eng = TriChefEngine()
    print(f"[local_bench] cache domains: {list(eng._cache.keys())}")

    report: dict = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "topk": TOPK,
        "configs": [c for c, _ in CONFIGS],
        "per_query": [],
        "summary_by_domain": {},
        "summary_overall": {},
    }

    # {config: {domain: {hits, returned}}, ...}
    per_dom: dict[str, dict[str, dict[str, int]]] = {
        name: {} for name, _ in CONFIGS
    }
    overall: dict[str, dict[str, int]] = {
        name: {"hits": 0, "returned": 0} for name, _ in CONFIGS
    }

    for q, dom, kws in EVAL_SET:
        if dom not in eng._cache:
            print(f"\n=== {dom} | '{q}' === SKIP (도메인 캐시 없음)")
            continue

        row = {"query": q, "domain": dom, "kws": kws, "configs": {}}
        print(f"\n=== {dom} | {q!r} ===")
        for cfg_name, flags in CONFIGS:
            try:
                hits = eng.search(q, domain=dom, topk=TOPK, **flags)
            except Exception as e:
                print(f"  [{cfg_name:14s}] ERROR: {e}")
                row["configs"][cfg_name] = {"error": str(e)[:200]}
                continue

            returned = len(hits)
            kw_hits = sum(1 for h in hits if _hit(h.id, kws))
            row["configs"][cfg_name] = {
                "returned": returned,
                "kw_hits":  kw_hits,
                "top": [{"id": h.id, "score": round(h.score, 4),
                          "conf": round(h.confidence, 4)} for h in hits[:3]],
            }
            print(f"  [{cfg_name:14s}] returned={returned}/{TOPK}  kw_hits={kw_hits}")
            for h in hits[:3]:
                mark = " *" if _hit(h.id, kws) else "  "
                print(f"    {mark} s={h.score:.3f} conf={h.confidence:.3f}  {h.id[:70]}")

            # aggregate
            overall[cfg_name]["hits"] += kw_hits
            overall[cfg_name]["returned"] += returned
            per_dom[cfg_name].setdefault(dom, {"hits": 0, "returned": 0})
            per_dom[cfg_name][dom]["hits"] += kw_hits
            per_dom[cfg_name][dom]["returned"] += returned

        report["per_query"].append(row)

    # summary 계산
    for cfg_name, _ in CONFIGS:
        report["summary_by_domain"][cfg_name] = {
            dom: {
                "hit_rate": round(v["hits"] / max(v["returned"], 1), 3),
                "hits": v["hits"], "returned": v["returned"],
            }
            for dom, v in per_dom[cfg_name].items()
        }
        o = overall[cfg_name]
        report["summary_overall"][cfg_name] = {
            "hit_rate": round(o["hits"] / max(o["returned"], 1), 3),
            "hits": o["hits"], "returned": o["returned"],
        }

    # 콘솔 요약 표
    print("\n" + "=" * 70)
    print(f"{'config':<16} {'overall':>10} " + " ".join(
        f"{d:>12}" for d in ("image", "doc_page", "movie", "music")
    ))
    print("-" * 70)
    for cfg_name, _ in CONFIGS:
        row_str = f"{cfg_name:<16} {report['summary_overall'][cfg_name]['hit_rate']:>10.3f} "
        for dom in ("image", "doc_page", "movie", "music"):
            v = report["summary_by_domain"][cfg_name].get(dom)
            row_str += f"{v['hit_rate']:>12.3f} " if v else f"{'--':>12} "
        print(row_str)

    # 저장
    out_dir = ROOT / "bench_results"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"{ts}_local_bench_all.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    main()
