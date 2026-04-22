"""scripts/smoke_search.py — v1 baseline E2E 검증 (threshold bypass)."""
from __future__ import annotations
import os, sys, json
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

# Windows 콘솔 UTF-8
sys.stdout.reconfigure(encoding="utf-8")

from config import PATHS  # noqa: E402
from services.trichef.unified_engine import TriChefEngine  # noqa: E402
from services.trichef import tri_gs, calibration  # noqa: E402

eng = TriChefEngine()
print("cache domains:", list(eng._cache.keys()))

for domain, q in [("image", "사람 얼굴"), ("doc_page", "환경 정책")]:
    print(f"\n=== {domain} | '{q}' ===")
    q_Re, q_Im = eng._embed_query(q)
    d = eng._cache[domain]
    scores = tri_gs.hermitian_score(
        q_Re[None, :], q_Im[None, :], q_Im[None, :],
        d["Re"], d["Im"], d["Z"],
    )[0]
    cal = calibration.get_thresholds(domain)
    print(f"abs_thr={cal['abs_threshold']:.4f} mu={cal['mu_null']:.4f} sig={cal['sigma_null']:.4f}")
    print(f"score range: max={scores.max():.4f} min={scores.min():.4f} mean={scores.mean():.4f}")
    order = np.argsort(-scores)[:5]
    for r, i in enumerate(order):
        print(f"{r+1}. score={scores[i]:.4f}  id={d['ids'][i]}")
