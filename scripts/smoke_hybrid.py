"""scripts/smoke_hybrid.py — v2 P2 Dense / Sparse / Hybrid 비교 (threshold bypass)."""
from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")
sys.stdout.reconfigure(encoding="utf-8")

from services.trichef.unified_engine import TriChefEngine, _rrf_merge  # noqa: E402
from services.trichef import tri_gs  # noqa: E402
from embedders.trichef import bgem3_sparse  # noqa: E402

eng = TriChefEngine()

def run(domain: str, q: str, topk: int = 5, pool: int = 200):
    d = eng._cache[domain]
    q_Re, q_Im = eng._embed_query(q)
    dense = tri_gs.hermitian_score(
        q_Re[None, :], q_Im[None, :], q_Im[None, :],
        d["Re"], d["Im"], d["Z"],
    )[0]
    dense_order = np.argsort(-dense)
    q_sp = bgem3_sparse.embed_query_sparse(q)
    lex = bgem3_sparse.lexical_scores(q_sp, d["sparse"])
    lex_order = np.argsort(-lex)
    rrf = _rrf_merge([dense_order[:pool], lex_order[:pool]], n=len(dense))
    rrf_order = np.argsort(-rrf)

    print(f"\n=== {domain} | '{q}' ===")
    print("-- Dense --")
    for i in dense_order[:topk]:
        print(f"  {dense[i]:.4f}  {d['ids'][i]}")
    print("-- Sparse --")
    for i in lex_order[:topk]:
        print(f"  {lex[i]:.4f}  {d['ids'][i]}")
    print("-- Hybrid RRF --")
    for i in rrf_order[:topk]:
        print(f"  rrf={rrf[i]:.4f} dense={dense[i]:.4f} lex={lex[i]:.4f}  {d['ids'][i]}")

for dom, q in [("image", "사람 얼굴"), ("doc_page", "환경 정책"),
               ("doc_page", "인공지능 교육"), ("doc_page", "탄소중립")]:
    run(dom, q)
