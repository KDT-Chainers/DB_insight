"""services/audio_check.py — 음성(Rec) 도메인 BGE-M3 일치성 검증 (Phase E-2).

audio (Rec) 도메인의 z-score CDF 부풀림 ("보이저호" → 다스뵈이다 dense 98%+) 차단.

원리:
  1) STT 텍스트 segment BGE-M3 임베딩 (cache_music_Im.npy) 캐시 활용
  2) 쿼리를 같은 BGE-M3 (e5_caption_im) 로 임베딩
  3) raw cosine 직접 측정 → 노이즈 분포 대비 페널티
  4) calibration.json 의 audio domain noise/relevant Beta 활용

API:
  audio_match(audio_id, query) -> float | None
  filter_by_audio_match(results, query) -> list[dict]
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

from config import PATHS

logger = logging.getLogger(__name__)


# 캘리브레이션 결과 (Phase E-1):
#   audio noise (BGE-M3): μ=0.211, σ=0.028
#   n=2.0σ → 0.267 / n=2.5σ → 0.281 / n=3.0σ → 0.295
# 실측: 보이저호 무관 음성 max audio_match=0.268 (n=2σ 바로 위) → 통과 부작용.
# default n=2.5σ → 보이저호 차단 + 정상 매칭(0.30+) 보존.
# Bayesian 은 relevant n 너무 작을 때 (Beta a<1 U-shape) 부정확 → 비활성 권장.
_DEFAULT_N_SIGMA = 3.5
_VISUAL_FLOOR_FALLBACK = 0.309  # n=3.5σ 추정값
_PENALTY_FACTOR = 0.3
# Bayesian dual-Beta 활성 여부 — relevant 샘플 충분(>30) 시에만 권장.
# 현재 audio relevant n=7 → 비활성 default. 환경변수 OMC_AUDIO_USE_BAYES=1 로 강제 가능.
_USE_BAYES_DEFAULT = False


def _get_calibrated_floor(n_sigma: float = _DEFAULT_N_SIGMA) -> float:
    try:
        cal_path = Path(__file__).parent / "calibration.json"
        if not cal_path.exists():
            return _VISUAL_FLOOR_FALLBACK
        cal = json.loads(cal_path.read_text(encoding="utf-8"))
        d = cal.get("audio") or {}
        irr = d.get("irrelevant") or d
        g = irr.get("gaussian") or {}
        mu = float(g.get("mu", 0.0))
        sigma = float(g.get("sigma", 0.0))
        if sigma <= 0:
            return _VISUAL_FLOOR_FALLBACK
        return mu + n_sigma * sigma
    except Exception:
        return _VISUAL_FLOOR_FALLBACK


_AUDIO_FLOOR_DEFAULT = _get_calibrated_floor(_DEFAULT_N_SIGMA)


def _get_runtime_floor() -> float:
    raw = os.environ.get("OMC_AUDIO_N_SIGMA", "").strip()
    if not raw:
        return _AUDIO_FLOOR_DEFAULT
    try:
        n = float(raw)
        return _get_calibrated_floor(n)
    except Exception:
        return _AUDIO_FLOOR_DEFAULT


# ── 캐시 ──────────────────────────────────────────────────────────────────────
class _Cache:
    audio_emb: Optional[np.ndarray] = None
    # 1:N — 같은 file 이 여러 segment row 가짐. 매칭 시 max cosine 사용.
    audio_id_to_rows: Optional[dict[str, list[int]]] = None
    loaded: bool = False
    enabled: bool = False


def _normalize_path(p: str) -> str:
    """absolute path 를 raw_DB/Rec/ 이후 상대경로로 정규화. backslash → /."""
    p = (p or "").replace("\\", "/")
    marker = "/raw_DB/Rec/"
    if marker in p:
        p = p.split(marker, 1)[1]
    return p


def _ensure_loaded() -> bool:
    if _Cache.loaded:
        return _Cache.enabled
    _Cache.loaded = True
    try:
        mu_path = PATHS.get("TRICHEF_MUSIC_CACHE")
        if not mu_path:
            logger.info("[audio_check] TRICHEF_MUSIC_CACHE 미설정 — 비활성")
            return False
        adir = Path(mu_path)
        emb_path = adir / "cache_music_Im.npy"
        ids_path = adir / "music_ids.json"
        if not emb_path.exists() or not ids_path.exists():
            logger.info("[audio_check] 캐시 파일 없음 — 비활성")
            return False
        emb = np.load(str(emb_path))
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        emb = (emb / np.maximum(norms, 1e-8)).astype(np.float32, copy=False)
        ids_data = json.loads(ids_path.read_text(encoding="utf-8"))
        ids = ids_data.get("ids") if isinstance(ids_data, dict) else ids_data
        if not isinstance(ids, list) or len(ids) != emb.shape[0]:
            logger.warning("[audio_check] ids 형식/길이 불일치 — 비활성")
            return False
        # 같은 파일 (다른 segment) 이 여러 row 가짐 → 1:N 매핑
        id_to_rows: dict[str, list[int]] = {}
        for i, _id in enumerate(ids):
            key = _normalize_path(str(_id))
            id_to_rows.setdefault(key, []).append(i)
        _Cache.audio_emb = emb
        _Cache.audio_id_to_rows = id_to_rows
        _Cache.enabled = True
        logger.info(f"[audio_check] 캐시 로드: shape={emb.shape}, "
                    f"unique_files={len(id_to_rows)} (rows={len(ids)})")
        return True
    except Exception as e:
        logger.warning(f"[audio_check] 로드 실패: {e}")
        return False


def _embed_query_text(query: str) -> Optional[np.ndarray]:
    try:
        from embedders.trichef import e5_caption_im
        emb = e5_caption_im.embed_query([query])
        if emb is None or len(emb) == 0:
            return None
        v = np.asarray(emb[0], dtype=np.float32)
        n = float(np.linalg.norm(v))
        if n < 1e-8:
            return None
        return v / n
    except Exception as e:
        logger.debug(f"[audio_check] embed 실패: {e}")
        return None


# ── Bayesian dual-Beta (audio 도메인) ─────────────────────────────────────────
class _BayesCache:
    rel: Optional[dict] = None
    irr: Optional[dict] = None
    prior_rel: float = 0.05
    loaded: bool = False
    enabled: bool = False


def _ensure_bayes_loaded() -> bool:
    if _BayesCache.loaded:
        return _BayesCache.enabled
    _BayesCache.loaded = True
    try:
        cal_path = Path(__file__).parent / "calibration.json"
        if not cal_path.exists():
            return False
        cal = json.loads(cal_path.read_text(encoding="utf-8"))
        d = cal.get("audio") or {}
        rel = (d.get("relevant") or {}).get("beta")
        irr = (d.get("irrelevant") or {}).get("beta") or d.get("beta")
        if not rel or not irr:
            logger.info("[audio_bayes] relevant/irrelevant Beta 미존재 — Bayesian 비활성")
            return False
        _BayesCache.rel = rel
        _BayesCache.irr = irr
        _BayesCache.enabled = True
        return True
    except Exception:
        return False


def _beta_pdf(x: float, params: dict) -> float:
    try:
        from scipy.stats import beta as _beta
        a = params["a"]; b = params["b"]
        loc = params.get("loc", 0.0); scale = params.get("scale", 1.0)
        if scale <= 0 or x < loc or x > loc + scale:
            return 0.0
        return float(_beta.pdf(x, a, b, loc=loc, scale=scale))
    except Exception:
        return 0.0


def bayesian_confidence(audio_match: float) -> Optional[float]:
    if not _ensure_bayes_loaded():
        return None
    p = _BayesCache.prior_rel
    pdf_rel = _beta_pdf(audio_match, _BayesCache.rel)
    pdf_irr = _beta_pdf(audio_match, _BayesCache.irr)
    num = pdf_rel * p
    den = pdf_rel * p + pdf_irr * (1.0 - p)
    if den <= 1e-12:
        if _BayesCache.rel and audio_match >= _BayesCache.rel.get("loc", 0):
            return 1.0
        return 0.0
    return num / den


def filter_by_audio_match(
    results: list[dict],
    query: str,
    floor: Optional[float] = None,
    penalty: float = _PENALTY_FACTOR,
) -> list[dict]:
    """audio 도메인 결과에 BGE-M3 일치성 검증 + 페널티."""
    if not results:
        return results
    if not _ensure_loaded():
        return results

    if floor is None:
        floor = _get_runtime_floor()
    # Bayesian 은 환경변수 명시 시에만 활성 (audio relevant n 부족으로 default 비활성)
    use_bayes = (os.environ.get("OMC_AUDIO_USE_BAYES", "").strip() == "1") and _ensure_bayes_loaded()

    txt_vec = _embed_query_text(query)
    if txt_vec is None:
        return results

    n_audio = 0
    n_penalized = 0
    n_missing = 0
    for r in results:
        if r.get("file_type") not in ("audio", "music"):
            continue
        n_audio += 1
        # AV 결과는 file_path (절대경로) 만 가짐. trichef_id 없음.
        rid = r.get("trichef_id") or r.get("id") or r.get("file_path")
        if not rid:
            continue
        # 절대경로 → 상대경로 정규화
        normalized = _normalize_path(str(rid))
        rows = _Cache.audio_id_to_rows.get(normalized)
        if not rows:
            # full match 실패 시 endsWith fallback (drive letter / 경로 차이 흡수)
            for key in _Cache.audio_id_to_rows:
                if normalized.endswith(key) or key.endswith(normalized):
                    rows = _Cache.audio_id_to_rows[key]
                    break
        if not rows:
            n_missing += 1
            continue
        # 같은 file 의 모든 segment row 중 max cosine (가장 유사한 부분)
        seg_cosines = _Cache.audio_emb[rows] @ txt_vec   # (S,)
        cos = float(seg_cosines.max())
        r["audio_match"] = round(cos, 4)

        if use_bayes:
            p_rel = bayesian_confidence(cos)
            if p_rel is not None:
                r["audio_bayes_p_rel"] = round(p_rel, 4)
                if p_rel < 0.5:
                    n_penalized += 1
                    soft_penalty = penalty + (1.0 - penalty) * (p_rel / 0.5)
                    for k in ("confidence", "dense", "similarity"):
                        if k in r and r[k] is not None:
                            r[k] = round(float(r[k]) * soft_penalty, 4)
                continue

        if cos < floor:
            n_penalized += 1
            for k in ("confidence", "dense", "similarity"):
                if k in r and r[k] is not None:
                    r[k] = round(float(r[k]) * penalty, 4)

    mode = "bayes" if use_bayes else f"floor={floor:.4f}"
    logger.info(
        f"[audio_check] audio={n_audio}, penalized={n_penalized}, "
        f"missing={n_missing}, mode={mode}"
    )
    return results
