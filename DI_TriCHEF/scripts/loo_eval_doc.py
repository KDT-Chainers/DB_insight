"""DI_TriCHEF/scripts/loo_eval_doc.py — doc_page Leave-One-Out self-retrieval eval.

Phase 4-2 cross-check. α 값별로 Recall@1 / Recall@5 / MRR@10 측정.

방식:
  * `_body_texts.json` (34170 페이지 본문) 에서 N 페이지 샘플
  * 쿼리 = body_text 의 앞 100자 (사용자가 본문을 일부 인용한 상황 모사)
  * 정답 = 해당 페이지의 id (doc_page_ids.json)
  * top-10 검색 후 자기 id 의 rank 측정

한계 (must read):
  * Im_body 는 동일 body text 로 임베딩 — 쿼리가 body 일부면 α 낮을수록 유리
    (α=0 은 circular 하게 거의 완벽히 자기검색). 이 지표는 "body 인용 검색"
    시나리오 품질을 측정할 뿐, 전반적 품질이 아님.
  * α=1.0 (fusion OFF) 은 caption Im 만 씀 — body 인용 쿼리에 불리함.
  * proxy keyword bench 와 함께 보고, 두 신호가 충돌할 때는 trade-off 판단.

결과: `DI_TriCHEF/results/{ts}_loo_eval_doc.json`
"""
from __future__ import annotations

import datetime
import json
import os
import random
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


N_SAMPLES = 150
SEED = 20260425
QUERY_CHARS = 100
TOPK = 10

ALPHAS = [0.20, 0.35, 0.50, 0.65, 1.00]
CONFIGS = [
    ("dense",        {"use_lexical": False, "use_asf": False}),
    ("dense+sparse", {"use_lexical": True,  "use_asf": False}),
    ("dense+sp+asf", {"use_lexical": True,  "use_asf": True}),
]


def _load_corpus() -> tuple[list[str], list[str]]:
    doc_dir = Path("../../Data/embedded_DB/Doc")
    bodies = json.loads((doc_dir / "_body_texts.json").read_text(encoding="utf-8"))
    ids_raw = json.loads((doc_dir / "doc_page_ids.json").read_text(encoding="utf-8"))
    ids = ids_raw["ids"] if isinstance(ids_raw, dict) else ids_raw
    assert len(bodies) == len(ids), f"body/ids mismatch: {len(bodies)} vs {len(ids)}"
    return bodies, ids


def _sample_queries(bodies: list[str], ids: list[str], n: int) -> list[tuple[str, str]]:
    rnd = random.Random(SEED)
    # body 가 최소 40자는 되어야 쿼리로 의미있음
    eligible = [i for i, b in enumerate(bodies) if isinstance(b, str) and len(b.strip()) >= 40]
    picks = rnd.sample(eligible, min(n, len(eligible)))
    out: list[tuple[str, str]] = []
    for i in picks:
        q = bodies[i].strip()[:QUERY_CHARS]
        out.append((q, ids[i]))
    return out


def _rank_of(hits, target_id: str) -> int:
    """1-based rank, 0 if not found."""
    for r, h in enumerate(hits, 1):
        if h.id == target_id:
            return r
    return 0


def _run_one_alpha(alpha: float, queries: list[tuple[str, str]]) -> dict:
    _cfg.TRICHEF_CFG["DOC_IM_ALPHA"] = alpha
    eng = TriChefEngine()
    out: dict = {"alpha": alpha,
                 "metrics": {c: {"r1": 0, "r5": 0, "mrr": 0.0, "missing": 0}
                             for c, _ in CONFIGS}}

    for q, gold in queries:
        for cname, flags in CONFIGS:
            try:
                hits = eng.search(q, domain="doc_page", topk=TOPK, **flags)
            except Exception:
                out["metrics"][cname]["missing"] += 1
                continue
            r = _rank_of(hits, gold)
            m = out["metrics"][cname]
            if r == 0:
                m["missing"] += 1
            else:
                if r == 1: m["r1"] += 1
                if r <= 5: m["r5"] += 1
                m["mrr"] += 1.0 / r

    n = len(queries)
    for c in out["metrics"]:
        m = out["metrics"][c]
        m["r1"] = round(m["r1"] / n, 4)
        m["r5"] = round(m["r5"] / n, 4)
        m["mrr"] = round(m["mrr"] / n, 4)
    return out


def main() -> None:
    bodies, ids = _load_corpus()
    print(f"[loo] corpus: {len(bodies)} pages")
    queries = _sample_queries(bodies, ids, N_SAMPLES)
    print(f"[loo] sampled {len(queries)} queries (first {QUERY_CHARS} chars of body)")
    print(f"[loo] α values: {ALPHAS}")

    report = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "domain": "doc_page",
        "n_samples": len(queries),
        "query_chars": QUERY_CHARS,
        "topk": TOPK,
        "alphas": ALPHAS,
        "results": [],
    }

    for a in ALPHAS:
        print(f"\n{'='*60}\n  α = {a:.2f}\n{'='*60}")
        res = _run_one_alpha(a, queries)
        report["results"].append(res)
        for c, m in res["metrics"].items():
            print(f"  [{c:14s}] R@1={m['r1']:.3f}  R@5={m['r5']:.3f}  "
                  f"MRR={m['mrr']:.3f}  miss={m['missing']}")

    # 요약 표 (R@5 기준)
    print("\n" + "=" * 76)
    print(f"{'α':>6}   " + "   ".join(
        f"{c+':R@5':>18}" for c, _ in CONFIGS))
    print("-" * 76)
    for r in report["results"]:
        line = f"{r['alpha']:>6.2f}   " + "   ".join(
            f"{r['metrics'][c]['r5']:>18.3f}" for c, _ in CONFIGS)
        print(line)

    out_dir = ROOT / "DI_TriCHEF" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"{ts}_loo_eval_doc.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    main()
