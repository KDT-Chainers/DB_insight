"""
security/mosaic_engine.py
──────────────────────────────────────────────────────────────────────────────
이미지 PII 영역 모자이크 처리 독립 엔진.

지원 엔진:
  cv2  (권장): GaussianBlur 기반. 자연스러운 블러 효과. opencv-python 필요.
  pil  (폴백): 픽셀화 기반. 추가 의존성 없음.

설정: config.MOSAIC_ENGINE = "cv2" | "pil"  (기본: "cv2")
엔진 교체 시 이 파일만 건드리면 됨 — result_card / preview_renderer 는 수정 불필요.

입력/출력 계약:
  apply_mosaic(image_path, pii_regions, engine) -> PIL.Image (메모리 전용)
  - 원본 파일 수정 금지, 디스크 저장 금지
  - bbox: EasyOCR 형식 [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]

디버깅:
  - MOSAIC_ENGINE 설정 값이 logger에 출력됨
  - 각 bbox 처리 결과가 debug 레벨로 기록됨
  - cv2 임포트 실패 시 자동 pil 폴백 + warning 로그
  - bbox 좌표 오류는 skip (크래시 없음)
  - engine 파라미터로 개별 호출 시 엔진 강제 지정 가능

ABC: [C] 렌더링 출력 생성만 담당. DB·외부통신 없음.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import config

logger = logging.getLogger(__name__)

# ── 지원 엔진 상수 ─────────────────────────────────────────────────────────────
ENGINE_CV2 = "cv2"
ENGINE_PIL = "pil"


# ──────────────────────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────────────────────

def apply_mosaic(
    image_path: str,
    pii_regions: Optional[List[List]] = None,
    engine: Optional[str] = None,
):
    """
    이미지 PII 영역에 모자이크를 적용하여 PIL Image를 반환한다.

    Args:
        image_path:  원본 이미지 경로 (읽기만, 수정 금지)
        pii_regions: bbox 목록 [[[x1,y1],[x2,y1],[x2,y2],[x1,y2]], ...]
                     None 또는 빈 리스트면 모자이크 미적용.
        engine:      "cv2" | "pil". None이면 config.MOSAIC_ENGINE 사용.

    Returns:
        PIL.Image (메모리 전용 — 호출 측에서 base64/저장 여부 결정)

    Raises:
        FileNotFoundError: 이미지 파일 없음
        ImportError:       필수 패키지 없음 (cv2 없으면 pil 폴백)
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"이미지 파일 없음: {image_path}")

    resolved_engine = (engine or getattr(config, "MOSAIC_ENGINE", ENGINE_CV2)).lower()
    logger.debug("[mosaic_engine] 사용 엔진: %s, 파일: %s", resolved_engine, path.name)

    img = _load_pil(path)

    if not pii_regions:
        logger.debug("[mosaic_engine] pii_regions 없음 → 모자이크 미적용")
        return img

    if resolved_engine == ENGINE_CV2:
        try:
            return _apply_cv2_blur(img, pii_regions)
        except ImportError:
            logger.warning(
                "[mosaic_engine] opencv-python 미설치 → PIL 픽셀화로 폴백. "
                "pip install opencv-python 으로 설치하면 cv2 엔진 사용 가능."
            )
            return _apply_pil_pixelate(img, pii_regions)

    return _apply_pil_pixelate(img, pii_regions)


# ──────────────────────────────────────────────────────────────────────────────
# 내부: 이미지 로딩
# ──────────────────────────────────────────────────────────────────────────────

def _load_pil(path: Path):
    """PIL Image를 RGB로 로드. HEIC는 pillow-heif 자동 등록."""
    from PIL import Image

    if path.suffix.lower() in {".heic", ".heif"}:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            logger.warning("[mosaic_engine] pillow-heif 미설치. HEIC 로드 실패 가능.")

    return Image.open(str(path)).convert("RGB")


# ──────────────────────────────────────────────────────────────────────────────
# 내부: cv2 엔진 (GaussianBlur)
# ──────────────────────────────────────────────────────────────────────────────

def _apply_cv2_blur(img, pii_regions: List[List]):
    """
    OpenCV GaussianBlur로 PII bbox 영역을 블러 처리.

    PIL RGB ↔ OpenCV BGR 변환 주의.
    블러 강도: kernel_size = 영역 크기의 1/5 (최소 15, 반드시 홀수)
    """
    import cv2
    import numpy as np
    from PIL import Image

    # PIL RGB → NumPy → OpenCV BGR
    img_array = np.array(img)
    img_bgr   = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    result    = img_bgr.copy()

    h_img, w_img = result.shape[:2]

    for idx, bbox in enumerate(pii_regions):
        try:
            x_coords = [int(p[0]) for p in bbox]
            y_coords = [int(p[1]) for p in bbox]
            x1 = max(0, min(x_coords))
            y1 = max(0, min(y_coords))
            x2 = min(w_img, max(x_coords))
            y2 = min(h_img, max(y_coords))

            if x2 <= x1 or y2 <= y1:
                logger.debug("[mosaic_engine] bbox[%d] 좌표 오류 skip: (%d,%d,%d,%d)", idx, x1, y1, x2, y2)
                continue

            region = result[y1:y2, x1:x2]

            # 블러 커널: 영역 크기 기반, 반드시 홀수
            rh, rw = region.shape[:2]
            ksize = max(15, min(rw, rh) // 5)
            if ksize % 2 == 0:
                ksize += 1

            blurred = cv2.GaussianBlur(region, (ksize, ksize), 0)
            result[y1:y2, x1:x2] = blurred
            logger.debug(
                "[mosaic_engine] cv2 bbox[%d] 블러 적용: (%d,%d)~(%d,%d) kernel=%d",
                idx, x1, y1, x2, y2, ksize,
            )

        except Exception as exc:
            logger.warning("[mosaic_engine] bbox[%d] 처리 오류 (skip): %s", idx, exc)
            continue

    # OpenCV BGR → NumPy RGB → PIL
    result_rgb = cv2.cvtColor(result, cv2.COLOR_BGR2RGB)
    return Image.fromarray(result_rgb)


# ──────────────────────────────────────────────────────────────────────────────
# 내부: PIL 엔진 (픽셀화 폴백)
# ──────────────────────────────────────────────────────────────────────────────

def _apply_pil_pixelate(img, pii_regions: List[List]):
    """
    PIL로 PII bbox 영역을 픽셀화 처리 (cv2 없을 때 폴백).

    1/10 크기로 축소 후 원래 크기로 확대 → 픽셀화 효과.
    """
    from PIL import Image

    result = img.copy()

    for idx, bbox in enumerate(pii_regions):
        try:
            x_coords = [int(p[0]) for p in bbox]
            y_coords = [int(p[1]) for p in bbox]
            x1 = max(0, min(x_coords))
            y1 = max(0, min(y_coords))
            x2 = min(result.width, max(x_coords))
            y2 = min(result.height, max(y_coords))

            if x2 <= x1 or y2 <= y1:
                logger.debug("[mosaic_engine] bbox[%d] 좌표 오류 skip", idx)
                continue

            region = result.crop((x1, y1, x2, y2))
            rw, rh = region.size
            small  = region.resize((max(1, rw // 10), max(1, rh // 10)), Image.BOX)
            mosaic = small.resize((rw, rh), Image.NEAREST)
            result.paste(mosaic, (x1, y1))
            logger.debug("[mosaic_engine] pil bbox[%d] 픽셀화 적용: (%d,%d)~(%d,%d)", idx, x1, y1, x2, y2)

        except Exception as exc:
            logger.warning("[mosaic_engine] bbox[%d] 처리 오류 (skip): %s", idx, exc)
            continue

    return result
