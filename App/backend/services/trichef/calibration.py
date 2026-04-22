"""services/trichef/calibration.py — Data-adaptive abs_threshold 재보정.

각 도메인별로 null 분포(무관 쿼리→DB 점수)를 추정하여
abs_thr = μ_null + Φ⁻¹(1−FAR)·σ_null 을 저장한다.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from config import PATHS, TRICHEF_CFG
from services.trichef import tri_gs

_CALIB_PATH = Path(PATHS["EMBEDDED_DB"]) / "trichef_calibration.json"


def _acklam_inv_phi(p: float) -> float:
    """표준정규 분위수의 Acklam 근사 (scipy 없이)."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
          4.374664141464968e+00,  2.938163982698783e+00]
    d = [ 7.784695709041462e-03,  3.224671290700398e-01,
          2.445134137142996e+00,  3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) \
               / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= ph:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q \
               / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) \
             / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def calibrate_domain(domain: str, Re: np.ndarray,
                     Im_perp: np.ndarray, Z_perp: np.ndarray) -> dict:
    """도메인 내 self-score 분포를 추정해 abs_threshold 저장.

    Null 분포 ≈ 서로 다른 ID 간 cross-score. 최대 1000 쌍 랜덤 추출.
    """
    N = Re.shape[0]
    if N < 2:
        return get_thresholds(domain)

    rng = np.random.default_rng(42)
    pairs = min(1000, N * (N - 1) // 2)
    i_idx = rng.integers(0, N, pairs)
    j_idx = rng.integers(0, N, pairs)
    mask = i_idx != j_idx
    i_idx = i_idx[mask]
    j_idx = j_idx[mask]

    scores = tri_gs.hermitian_score(
        Re[i_idx], Im_perp[i_idx], Z_perp[i_idx],
        Re[j_idx], Im_perp[j_idx], Z_perp[j_idx],
    ).diagonal()
    mu  = float(scores.mean())
    sig = float(scores.std())

    far_key = "FAR_IMG" if domain == "image" else (
        "FAR_DOC_TEXT" if domain == "doc_text" else "FAR_DOC_PAGE"
    )
    FAR = TRICHEF_CFG[far_key]
    thr = mu + _acklam_inv_phi(1 - FAR) * sig

    data = _load_all()
    data[domain] = {
        "mu_null": mu, "sigma_null": sig,
        "abs_threshold": thr, "far": FAR,
        "N": N,
    }
    _CALIB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return data[domain]


def _load_all() -> dict:
    if _CALIB_PATH.exists():
        return json.loads(_CALIB_PATH.read_text(encoding="utf-8"))
    return {}


def get_thresholds(domain: str) -> dict:
    return _load_all().get(domain, {"mu_null": 0.0, "sigma_null": 1.0,
                                    "abs_threshold": 0.5})
