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
# 한국어 쿼리 실측 (RTX 4070, SigLIP2-Re, "박스 속에 들어있는 고양이"):
#   진짜 박스 안 고양이 (IMG_1356/IMG_1425/IMG_1367): cosine 0.14~0.16
#   인형 (cat_doll_34) — 진짜 고양이+인형 혼잡: 0.010
#   사자상 (real_cat_31/33): -0.05 ~ -0.06
#   강아지 (real_cat_32): -0.007
# 명확한 분리선 ~0.05. SigLIP2 한국어 cosine 절대값이 영어보다 낮음.
# floor 0.05 = 사자상/강아지 차단, 진짜 고양이 통과.
_VISUAL_FLOOR_DEFAULT = 0.05

# 페널티 계수 — floor 미만 시 confidence/dense/similarity 에 곱함.
# 0.3 = ~70% 감점. 완전 cut(0.0) 대신 페널티로 후순위 이동 유도.
# 추후 정렬 키(유사도 우선)에서 자연스럽게 밀려남.
_PENALTY_FACTOR = 0.3


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


def filter_by_visual_match(
    results: list[dict],
    query: str,
    floor: float = _VISUAL_FLOOR_DEFAULT,
    penalty: float = _PENALTY_FACTOR,
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
        if cos < floor:
            n_penalized += 1
            for k in ("confidence", "dense", "similarity"):
                if k in r and r[k] is not None:
                    r[k] = round(float(r[k]) * penalty, 4)

    logger.info(
        f"[visual_check] image={n_image}, penalized={n_penalized}, "
        f"missing_in_cache={n_missing}, floor={floor}"
    )
    return results
