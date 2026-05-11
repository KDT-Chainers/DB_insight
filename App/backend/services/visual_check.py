"""services/visual_check.py — 이미지 시각-텍스트 일치성 검증.

캡션이 거짓 키워드를 포함하더라도 SigLIP2 이미지 임베딩 ↔ 쿼리 텍스트 임베딩의
raw cosine 으로 의미 일치 여부를 직접 검사한다. 사자상이 "고양이가 누워 쉬는..."
캡션을 가져도 SigLIP2 image embedding 은 사자 모양을 반영 → "고양이" text
embedding 과 cosine 낮음 → 페널티/차단.

배경:
  현재 검색 결과의 dense (UI '유사도') 는 BGE-M3 + SigLIP2 fusion 점수라
  캡션 텍스트 매칭에 영향받음. 캡션이 거짓이면 dense 도 거짓.
  SigLIP2 image embedding 단독 ↔ 쿼리 cosine 은 캡션 무관 — 시각 ground truth.

API:
  visual_match_image(image_id, query) -> float | None
  filter_by_visual_match(results, query) -> list[dict]   (in-place + 반환)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from config import PATHS

logger = logging.getLogger(__name__)


# 도메인별 시각 일치성 floor (SigLIP2 raw cosine).
# Phase 1 캘리브레이션 (scripts/fit_calibration_distributions.py) 결과:
#   image domain 258,120 샘플 → μ=0.0139, σ=0.0328 (Beta a=12.81, b=10.85)
#   n×σ 임계값: n=1.0 → 0.047, n=1.5 → 0.063, n=2.0 → 0.080
#   p95 분위수 = 0.066 (≈ n=1.5σ 와 일치)
# 실측 케이스:
#   진짜 박스고양이/햄버거: visual 0.11~0.16 (모든 n 통과)
#   사자상/강아지/인형: -0.05~+0.02 (모든 n 차단)
#   cat_doll_34 (실제 고양이+인형): 0.066 (n=1.5 보더라인)
# n×σ sweep 검증 (실측):
#   n=1.0/1.5: cat_doll_34 (인형+고양이 혼합, vm=0.066) 통과 → 모호한 결과 잔존
#   n=2.0   : cat_doll_34 차단 → F99AB2B3 (명확한 고양이) top 부상 ✓
#   n=2.5/3.0: 동일 결과 (이미 깔끔), 더 엄격해도 회귀 없음
# default n=2.0 (p98.5 분위수, noise 98.5% 차단). 환경변수 OMC_VISUAL_N_SIGMA 로 조정 가능.
# calibration.json 미존재 시 fallback: 0.05 (이전 휴리스틱 값).
_VISUAL_FLOOR_FALLBACK = 0.05
_DEFAULT_N_SIGMA = 2.0  # 데이터셋 최적값 (n sweep 검증 결과)


def _get_calibrated_floor(domain: str = "image", n_sigma: float = _DEFAULT_N_SIGMA) -> float:
    """calibration.json 에서 mu + n*sigma 임계값 계산. 실패 시 fallback.

    v2 calibration.json (relevant + irrelevant 분리 후) 호환:
      - cal[domain]["irrelevant"]["gaussian"] 우선 사용
      - 없으면 cal[domain]["gaussian"] (v1 호환)
    """
    try:
        cal_path = Path(__file__).parent / "calibration.json"
        if not cal_path.exists():
            return _VISUAL_FLOOR_FALLBACK
        cal = json.loads(cal_path.read_text(encoding="utf-8"))
        d = cal.get(domain) or {}
        # v2: irrelevant 명시 / v1: 도메인 root 에 직접
        irr = d.get("irrelevant") or d
        g = irr.get("gaussian") or {}
        mu = float(g.get("mu", 0.0))
        sigma = float(g.get("sigma", 0.0))
        if sigma <= 0:
            return _VISUAL_FLOOR_FALLBACK
        return mu + n_sigma * sigma
    except Exception:
        return _VISUAL_FLOOR_FALLBACK


_VISUAL_FLOOR_DEFAULT = _get_calibrated_floor("image", _DEFAULT_N_SIGMA)


# ── [Phase B] Bayesian dual-Beta confidence ──────────────────────────────────
class _BayesCache:
    """relevant + irrelevant Beta 분포 + prior — lazy 로드."""
    rel: Optional[dict] = None      # {"a", "b", "loc", "scale", "gaussian":{...}}
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
        img = cal.get("image") or {}
        rel = (img.get("relevant") or {}).get("beta")
        irr = (img.get("irrelevant") or {}).get("beta") or img.get("beta")
        if not rel or not irr:
            logger.info("[bayes] relevant 또는 irrelevant Beta 분포 미존재 — Bayesian 비활성")
            return False
        _BayesCache.rel = rel
        _BayesCache.irr = irr
        _BayesCache.enabled = True
        logger.info(f"[bayes] 활성: rel a={rel['a']} b={rel['b']}, "
                    f"irr a={irr['a']} b={irr['b']}, prior_rel={_BayesCache.prior_rel}")
        return True
    except Exception as e:
        logger.warning(f"[bayes] 로드 실패: {e}")
        return False


def _beta_pdf(x: float, params: dict) -> float:
    """Beta(a, b, loc, scale) pdf 값 반환. scipy 사용. 범위 외는 0."""
    try:
        from scipy.stats import beta as _beta
        a = params["a"]; b = params["b"]
        loc = params.get("loc", 0.0); scale = params.get("scale", 1.0)
        if scale <= 0 or x < loc or x > loc + scale:
            return 0.0
        return float(_beta.pdf(x, a, b, loc=loc, scale=scale))
    except Exception:
        return 0.0


def bayesian_confidence(visual_match: float, prior_rel: Optional[float] = None) -> Optional[float]:
    """SigLIP2 visual_match 값 → P(relevant | visual_match) 베이즈 확률.

    Args:
        visual_match: SigLIP2 image-text raw cosine.
        prior_rel: P(relevant). 미지정 시 default 0.05.

    Returns:
        float in [0, 1]: P(rel | visual_match). dual-Beta likelihood ratio.
        None: Bayesian 비활성 또는 계산 불가.
    """
    if not _ensure_bayes_loaded():
        return None
    p = prior_rel if prior_rel is not None else _BayesCache.prior_rel
    pdf_rel = _beta_pdf(visual_match, _BayesCache.rel)
    pdf_irr = _beta_pdf(visual_match, _BayesCache.irr)
    num = pdf_rel * p
    den = pdf_rel * p + pdf_irr * (1.0 - p)
    if den <= 1e-12:
        # 두 분포 모두 0 — visual_match 가 두 분포 범위 밖. relevant 범위(0.08~0.17) 위면 1, 아래면 0.
        if _BayesCache.rel and visual_match >= _BayesCache.rel.get("loc", 0):
            return 1.0
        return 0.0
    return num / den

# 페널티 계수 — floor 미만 시 confidence/dense/similarity 에 곱함.
# 0.3 = ~70% 감점. 완전 cut(0.0) 대신 페널티로 후순위 이동 유도.
# 추후 정렬 키(유사도 우선)에서 자연스럽게 밀려남.
# OMC_VISUAL_PENALTY 환경변수로 0.0~1.0 사이 값 override 가능 (sweep 실험용).
def _get_default_penalty() -> float:
    import os as _os_p
    raw = _os_p.environ.get("OMC_VISUAL_PENALTY", "").strip()
    if raw:
        try:
            v = float(raw)
            if 0.0 <= v <= 1.0:
                return v
        except Exception:
            pass
    return 0.3
_PENALTY_FACTOR = _get_default_penalty()


class _Cache:
    img_emb: Optional[np.ndarray] = None       # (N, D) L2-normalized
    img_id_to_row: Optional[dict] = None       # str id → int row
    loaded: bool = False
    enabled: bool = False


def _ensure_loaded() -> bool:
    """이미지 캐시 lazy 로드. 첫 호출 시 npy + ids.json 읽기."""
    if _Cache.loaded:
        return _Cache.enabled
    _Cache.loaded = True

    try:
        idir = Path(PATHS["TRICHEF_IMG_CACHE"])
        emb_path = idir / "cache_img_Re_siglip2.npy"
        ids_path = idir / "img_ids.json"
        if not emb_path.exists() or not ids_path.exists():
            logger.warning("[visual_check] 캐시 파일 없음 — 시각 검증 비활성")
            return False

        emb = np.load(str(emb_path))
        # L2 normalize for cosine
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        emb = (emb / np.maximum(norms, 1e-8)).astype(np.float32, copy=False)

        ids_data = json.loads(ids_path.read_text(encoding="utf-8"))
        ids = ids_data.get("ids") if isinstance(ids_data, dict) else ids_data
        if not isinstance(ids, list):
            logger.warning("[visual_check] img_ids.json 형식 미지원")
            return False
        if len(ids) != emb.shape[0]:
            logger.warning(
                f"[visual_check] id 수({len(ids)}) ≠ 임베딩 수({emb.shape[0]}) — 비활성"
            )
            return False

        _Cache.img_emb = emb
        _Cache.img_id_to_row = {str(_id): i for i, _id in enumerate(ids)}
        _Cache.enabled = True
        logger.info(
            f"[visual_check] 캐시 로드 완료: shape={emb.shape}, ids={len(ids)}"
        )
        return True
    except Exception as e:
        logger.exception(f"[visual_check] 로드 실패: {e}")
        return False


def _embed_query_text(query: str) -> Optional[np.ndarray]:
    """쿼리를 SigLIP2 text encoder 로 임베딩 (L2 normalized 1D)."""
    try:
        from embedders.trichef import siglip2_re
        emb = siglip2_re.embed_texts([query])
        if emb is None or len(emb) == 0:
            return None
        v = np.asarray(emb[0], dtype=np.float32)
        n = float(np.linalg.norm(v))
        if n < 1e-8:
            return None
        return v / n
    except Exception as e:
        logger.debug(f"[visual_check] embed_texts 실패: {e}")
        return None


def visual_match_image(image_id: str, query: str) -> Optional[float]:
    """단일 이미지의 시각-쿼리 cosine 반환.

    Args:
        image_id: img_ids.json 에 있는 id 문자열 (예: 'YS_1차/foo.jpg').
        query: 사용자 쿼리.

    Returns:
        float in [-1, 1]: SigLIP2 image-text raw cosine.
        None: 캐시 없음 / id 미존재 / 임베딩 실패.
    """
    if not _ensure_loaded():
        return None
    row = _Cache.img_id_to_row.get(image_id) if _Cache.img_id_to_row else None
    if row is None:
        return None
    img_vec = _Cache.img_emb[row]                  # already normalized
    txt_vec = _embed_query_text(query)
    if txt_vec is None:
        return None
    return float(np.dot(img_vec, txt_vec))


def _get_runtime_floor() -> float:
    """런타임 환경변수 OMC_VISUAL_N_SIGMA 로 n 값 조정 — n sweep 실험용.
    예: OMC_VISUAL_N_SIGMA=2.0 → n=2σ 적용. 미설정 시 default 1.5."""
    import os as _os
    raw = _os.environ.get("OMC_VISUAL_N_SIGMA", "").strip()
    if not raw:
        return _VISUAL_FLOOR_DEFAULT
    try:
        n = float(raw)
        return _get_calibrated_floor("image", n)
    except Exception:
        return _VISUAL_FLOOR_DEFAULT


def filter_by_visual_match(
    results: list[dict],
    query: str,
    floor: Optional[float] = None,
    penalty: float = _PENALTY_FACTOR,
    use_bayes: bool = True,
) -> list[dict]:
    """검색 결과의 image 도메인 항목에 시각 일치성 검증 적용.

    동작:
      - 각 image 결과에 visual_match (float) 필드 추가.
      - visual_match < floor 인 경우 confidence/dense/similarity 에 penalty 계수 곱함.
      - floor 통과 시 페널티 없음.
      - cut 대신 페널티 — 사용자가 보고 판단할 수 있도록 결과 보존.

    캡션 거짓말 시나리오:
      사자상 (캡션은 "고양이가 누워...") visual_match ~0.18 < 0.20 → penalty 0.3
      → confidence 99.7% × 0.3 = 29.9%, dense 82.8% × 0.3 = 24.8%
      → 정렬 key (dense 우선) 에서 후순위로 밀려남.
    """
    if not results:
        return results
    if not _ensure_loaded():
        logger.debug("[visual_check] 비활성 — 결과 그대로 반환")
        return results

    # floor 미지정 시 runtime 환경변수 또는 캘리브레이션 default 사용
    if floor is None:
        floor = _get_runtime_floor()

    # [Phase B] Bayesian dual-Beta 활성 시 P(rel|vm) 기반 페널티 (더 정직).
    #   비활성 시 floor + penalty 휴리스틱 (기존 v15.1 동작).
    # [v3 A/B] OMC_VISUAL_USE_BAYES=0 으로 floor 모드 강제 가능 (default "1" 호환).
    import os as _os_bayes
    _bayes_env = _os_bayes.environ.get("OMC_VISUAL_USE_BAYES", "1").strip()
    use_bayes = use_bayes and (_bayes_env != "0") and _ensure_bayes_loaded()

    txt_vec = _embed_query_text(query)
    if txt_vec is None:
        logger.debug("[visual_check] 쿼리 임베딩 실패 — skip")
        return results

    n_image = 0
    n_penalized = 0
    n_missing = 0
    for r in results:
        if r.get("file_type") != "image":
            continue
        n_image += 1
        rid = r.get("trichef_id") or r.get("id")
        if not rid:
            continue
        row = _Cache.img_id_to_row.get(str(rid))
        if row is None:
            n_missing += 1
            continue
        img_vec = _Cache.img_emb[row]
        cos = float(np.dot(img_vec, txt_vec))
        r["visual_match"] = round(cos, 4)

        if use_bayes:
            # Bayesian P(rel | visual_match) 계산 → 점수 변환
            p_rel = bayesian_confidence(cos)
            if p_rel is not None:
                r["bayes_p_rel"] = round(p_rel, 4)
                # P(rel) < 0.5 → 무관 가능성 큼 → 페널티 (P(rel) 비율로 부드럽게)
                if p_rel < 0.5:
                    n_penalized += 1
                    # 부드러운 페널티: 0.3 ~ 1.0 사이로 P(rel) 에 비례
                    # P(rel)=0.0 → 0.3 (강한 페널티), P(rel)=0.5 → 0.65, P(rel)=0.999 → 1.0
                    soft_penalty = penalty + (1.0 - penalty) * (p_rel / 0.5)
                    for k in ("confidence", "dense", "similarity"):
                        if k in r and r[k] is not None:
                            r[k] = round(float(r[k]) * soft_penalty, 4)
                continue

        # Bayesian 비활성 또는 계산 실패 → 기존 floor 휴리스틱
        if cos < floor:
            n_penalized += 1
            for k in ("confidence", "dense", "similarity"):
                if k in r and r[k] is not None:
                    r[k] = round(float(r[k]) * penalty, 4)

    mode = "bayes" if use_bayes else f"floor={floor:.4f}"
    logger.info(
        f"[visual_check] image={n_image}, penalized={n_penalized}, "
        f"missing_in_cache={n_missing}, mode={mode}"
    )
    return results
