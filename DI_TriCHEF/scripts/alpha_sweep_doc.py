"""DI_TriCHEF/scripts/alpha_sweep_doc.py — doc_page Im_body fusion α 튜닝 벤치.

Phase 4-2. α ∈ {0.20, 0.35(default), 0.50, 0.65, 1.00(fusion OFF)} 비교.
각 α 마다 TriChefEngine 새로 생성 (캐시 로드 시점에 Im_fused 가 반영되므로 재로딩 필요).
서버/Flask 없음. proxy precision = top-K 결과 id 에 기대 키워드 포함 비율.

결과: `DI_TriCHEF/results/{ts}_alpha_sweep_doc.json`
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as _cfg  # noqa: E402
from services.trichef.unified_engine import TriChefEngine  # noqa: E402


QUERIES: list[tuple[str, list[str]]] = [
    ("환경 정책",     ["환경", "정책", "기후", "탄소", "그린"]),
    ("인공지능 교육", ["인공지능", "AI", "교육", "SW", "소프트웨어"]),
    ("탄소중립",      ["탄소", "중립", "기후", "환경", "ESG"]),
    ("디지털 전환",   ["디지털", "전환", "DX", "SW", "ICT"]),
    ("반도체 산업",   ["반도체", "산업", "Samsung", "하이닉스"]),
]

ALPHAS = [0.20, 0.35, 0.50, 0.65, 1.00]  # 1.00 = pure caption (fusion off)
TOPK = 5
CONFIGS = [
    ("dense",        {"use_lexical": False, "use_asf": False}),
    ("dense+sparse", {"use_lexical": True,  "use_asf": False}),
    ("dense+sp+asf", {"use_lexical": True,  "use_asf": True}),
]


def _hit(id_str: str, kws: list[str]) -> bool:
    low = id_str.lower()
    return any(k.lower() in low for k in kws)


def _run_one_alpha(alpha: float) -> dict:
    _cfg.TRICHEF_CFG["DOC_IM_ALPHA"] = alpha
    # 엔진 새 인스턴스 — _cache 는 인스턴스 상태이므로 신규 α 로 Im_fused 재적용됨
    eng = TriChefEngine()
    out: dict = {"alpha": alpha, "per_query": [],
                 "summary": {c: {"hits": 0, "returned": 0} for c, _ in CONFIGS}}

    for q, kws in QUERIES:
        row: dict = {"query": q, "configs": {}}
        for cname, flags in CONFIGS:
            try:
                hits = eng.search(q, domain="doc_page", topk=TOPK, **flags)
            except Exception as e:
                row["configs"][cname] = {"error": str(e)[:200]}
                continue
            ret = len(hits)
            kw = sum(1 for h in hits if _hit(h.id, kws))
            row["configs"][cname] = {
                "returned": ret, "kw_hits": kw,
                "top": [{"id": h.id, "score": round(h.score, 4)}
                        for h in hits[:3]],
            }
            out["summary"][cname]["hits"] += kw
            out["summary"][cname]["returned"] += ret
        out["per_query"].append(row)

    for c in out["summary"]:
        s = out["summary"][c]
        s["hit_rate"] = round(s["hits"] / max(s["returned"], 1), 3)
    return out


def main() -> None:
    print(f"[alpha_sweep] α values: {ALPHAS}")
    print(f"[alpha_sweep] {len(QUERIES)} queries × {len(CONFIGS)} configs "
          f"× {len(ALPHAS)} α = {len(QUERIES)*len(CONFIGS)*len(ALPHAS)} searches")

    report: dict = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "domain": "doc_page",
        "topk": TOPK,
        "alphas": ALPHAS,
        "results": [],
    }

    for a in ALPHAS:
        print(f"\n{'='*60}\n  α = {a:.2f}\n{'='*60}")
        res = _run_one_alpha(a)
        report["results"].append(res)
        for cname, s in res["summary"].items():
            print(f"  [{cname:14s}] hit_rate={s['hit_rate']:.3f} "
                  f"({s['hits']}/{s['returned']})")

    # 요약 표
    print("\n" + "=" * 72)
    hdr = f"{'α':>6} " + " ".join(f"{c:>14}" for c, _ in CONFIGS)
    print(hdr)
    print("-" * 72)
    for r in report["results"]:
        line = f"{r['alpha']:>6.2f} " + " ".join(
            f"{r['summary'][c]['hit_rate']:>14.3f}" for c, _ in CONFIGS
        )
        print(line)

    out_dir = ROOT / "DI_TriCHEF" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"{ts}_alpha_sweep_doc.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    main()
