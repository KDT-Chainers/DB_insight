"""services/trichef/calibration.py — Data-adaptive abs_threshold 재보정.

각 도메인별로 null 분포(무관 쿼리→DB 점수)를 추정하여
abs_thr = μ_null + Φ⁻¹(1−FAR)·σ_null 을 저장한다.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np

from config import PATHS, TRICHEF_CFG
from services.trichef import tri_gs

logger = logging.getLogger(__name__)

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

    scores = tri_gs.pair_hermitian_score(
        Re[i_idx], Im_perp[i_idx], Z_perp[i_idx],
        Re[j_idx], Im_perp[j_idx], Z_perp[j_idx],
    )
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


def calibrate_crossmodal(domain: str,
                         captions: list[str],
                         Re: np.ndarray, Im_perp: np.ndarray,
                         Z_perp: np.ndarray,
                         sample_q: int = 200,
                         pairs_per_q: int = 5) -> dict:
    """W5-3: 도메인 일반화된 cross-modal null calibration.

    domain ∈ {"image", "doc_page"}. FAR 는 각 도메인 설정 사용.
    """
    import random
    from embedders.trichef import siglip2_re
    from embedders.trichef import bgem3_caption_im as im_embedder

    N = Re.shape[0]
    if N < 10 or len(captions) < 10:
        return get_thresholds(domain)

    rng = random.Random(42)
    nprng = np.random.default_rng(42)

    non_empty = [(i, c) for i, c in enumerate(captions) if c and c.strip()]
    if len(non_empty) < 10:
        return get_thresholds(domain)
    sample = rng.sample(non_empty, min(sample_q, len(non_empty)))
    src_idx = [i for i, _ in sample]
    texts   = [c.strip()[:500] for _, c in sample]

    q_Re = siglip2_re.embed_texts(texts)
    q_Re = q_Re / (np.linalg.norm(q_Re, axis=1, keepdims=True) + 1e-12)
    q_Im = im_embedder.embed_query(texts) if hasattr(im_embedder, "embed_query") \
           else im_embedder.embed_passage(texts)
    q_Im = q_Im / (np.linalg.norm(q_Im, axis=1, keepdims=True) + 1e-12)
    q_Z  = q_Im

    scores: list[float] = []
    for k, i_src in enumerate(src_idx):
        j_idx = nprng.integers(0, N, pairs_per_q * 3)
        j_idx = j_idx[j_idx != i_src][:pairs_per_q]
        if len(j_idx) == 0:
            continue
        s = tri_gs.hermitian_score(
            q_Re[k:k+1], q_Im[k:k+1], q_Z[k:k+1],
            Re[j_idx], Im_perp[j_idx], Z_perp[j_idx],
        )[0]
        scores.extend(float(x) for x in s)

    arr = np.array(scores, dtype=np.float32)
    mu  = float(arr.mean())
    sig = float(arr.std())
    far_key = "FAR_IMG" if domain == "image" else (
        "FAR_DOC_TEXT" if domain == "doc_text" else "FAR_DOC_PAGE"
    )
    FAR = TRICHEF_CFG[far_key]
    thr = mu + _acklam_inv_phi(1 - FAR) * sig

    data = _load_all()

    # [W5-SAFETY 2026-04-24] thr 이 기존값의 2배 이상으로 폭증하는 경우 거부.
    # W5-3 doc_page 사례에서 within-doc caption 상관이 μ/σ 를 오염시켜 thr 0.205→0.355
    # 로 치솟았고 전 쿼리가 zero-hit 이 됨. 이런 "가짜 calibration" 자동 차단.
    prev = data.get(domain, {})
    prev_thr = float(prev.get("abs_threshold", 0.0) or 0.0)
    if prev_thr > 0 and thr > prev_thr * 2.0:
        logger.warning(
            f"[calibration:{domain}] REJECTED new thr {thr:.4f} > 2× prev {prev_thr:.4f}. "
            f"Keeping previous calibration. (new mu={mu:.4f} sig={sig:.4f})"
        )
        return prev

    data[domain] = {
        "mu_null": mu, "sigma_null": sig,
        "abs_threshold": thr, "far": FAR,
        "N": N, "method": "crossmodal_v1",
        "n_queries": len(src_idx), "n_pairs": len(arr),
    }
    _CALIB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return data[domain]


def calibrate_image_crossmodal(captions: list[str],
                               Re: np.ndarray, Im_perp: np.ndarray,
                               Z_perp: np.ndarray,
                               sample_q: int = 200,
                               pairs_per_q: int = 5) -> dict:
    """W4-1: query(text) ↔ doc(image) 크로스모달 null 분포 측정.

    기존 `calibrate_domain` 은 doc-doc 이미지 유사도를 측정해 query-doc
    스케일과 불일치(μ 과대 추정). 본 함수는 캡션 K개를 pseudo-query 로 사용하여
    실제 검색 경로와 동일하게 (SigLIP2 텍스트, BGE-M3 쿼리) 인코딩한 뒤,
    무작위 non-self 이미지와의 hermitian_score 분포를 측정한다.
    """
    import random
    from embedders.trichef import siglip2_re
    from embedders.trichef import bgem3_caption_im as im_embedder

    N = Re.shape[0]
    if N < 10 or len(captions) < 10:
        return get_thresholds("image")

    rng = random.Random(42)
    nprng = np.random.default_rng(42)

    # K개 pseudo-query 선택 (빈 캡션 제외)
    non_empty = [(i, c) for i, c in enumerate(captions) if c and c.strip()]
    if len(non_empty) < 10:
        return get_thresholds("image")
    sample = rng.sample(non_empty, min(sample_q, len(non_empty)))
    src_idx = [i for i, _ in sample]
    texts   = [c.strip()[:500] for _, c in sample]

    # 쿼리 임베딩 (배치)
    q_Re = siglip2_re.embed_texts(texts)
    q_Re = q_Re / (np.linalg.norm(q_Re, axis=1, keepdims=True) + 1e-12)
    q_Im = im_embedder.embed_query(texts) if hasattr(im_embedder, "embed_query") \
           else im_embedder.embed_passage(texts)
    q_Im = q_Im / (np.linalg.norm(q_Im, axis=1, keepdims=True) + 1e-12)
    q_Z  = q_Im

    # 각 쿼리당 pairs_per_q 개 non-self 문서와 pair score
    scores: list[float] = []
    for k, i_src in enumerate(src_idx):
        j_idx = nprng.integers(0, N, pairs_per_q * 3)
        j_idx = j_idx[j_idx != i_src][:pairs_per_q]
        if len(j_idx) == 0:
            continue
        s = tri_gs.hermitian_score(
            q_Re[k:k+1], q_Im[k:k+1], q_Z[k:k+1],
            Re[j_idx], Im_perp[j_idx], Z_perp[j_idx],
        )[0]
        scores.extend(float(x) for x in s)

    arr = np.array(scores, dtype=np.float32)
    mu  = float(arr.mean())
    sig = float(arr.std())
    FAR = TRICHEF_CFG["FAR_IMG"]
    thr = mu + _acklam_inv_phi(1 - FAR) * sig

    data = _load_all()
    data["image"] = {
        "mu_null": mu, "sigma_null": sig,
        "abs_threshold": thr, "far": FAR,
        "N": N, "method": "crossmodal_v1",
        "n_queries": len(src_idx), "n_pairs": len(arr),
    }
    _CALIB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return data["image"]


def _load_all() -> dict:
    if _CALIB_PATH.exists():
        return json.loads(_CALIB_PATH.read_text(encoding="utf-8"))
    return {}


def get_thresholds(domain: str) -> dict:
    return _load_all().get(domain, {"mu_null": 0.0, "sigma_null": 1.0,
                                    "abs_threshold": 0.5})
