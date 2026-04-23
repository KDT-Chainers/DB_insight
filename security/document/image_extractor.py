"""
document/image_extractor.py
──────────────────────────────────────────────────────────────────────────────
이미지 파일에서 OCR 로 텍스트 및 바운딩 박스 추출.

지원 포맷: PNG, JPG, JPEG, HEIC, WEBP
OCR 엔진: EasyOCR (영어 + 한국어)

주요 기능:
  - extract_image_with_regions(): 텍스트 + OCR bbox 반환 (PII 모자이크 처리용)
  - extract_image():              하위 호환 래퍼 (텍스트만 반환)
  - map_pii_to_image_regions():   PII 오프셋 → 이미지 bbox 매핑

전처리:
  - 너무 작은 이미지 업스케일 (최소 1200px)
  - 대비 강화 (2.0) → OCR 정확도 향상
  - HEIC: pillow-heif 로 PIL 에 등록
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

_MIN_TEXT_LENGTH = 5

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heic", ".webp"}


# ──────────────────────────────────────────────────────────────────────────────
# PIL 로딩 헬퍼
# ──────────────────────────────────────────────────────────────────────────────

def _load_image_pil(path: Path):
    """
    PIL Image 를 RGB 로 로드.
    HEIC/HEIF 포맷은 pillow-heif 를 통해 지원.
    """
    from PIL import Image

    ext = path.suffix.lower()
    if ext in {".heic", ".heif"}:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError as exc:
            raise ImportError(
                "HEIC 파일 지원을 위해 pillow-heif 설치 필요: "
                "pip install pillow-heif"
            ) from exc

    return Image.open(path).convert("RGB")


def _preprocess_image(img):
    """
    OCR 전처리: 업스케일 + 대비 강화 + 그레이스케일.

    그레이스케일 변환 이유:
      빨간 도장(stamp), 물도장, 컬러 배경이 겹친 문서에서
      색상 채널이 OCR을 혼동시킬 수 있다.
      그레이스케일로 변환하면 색상 간섭이 사라지고
      밝기 대비만 남아 숫자/텍스트 인식률이 높아진다.
    """
    from PIL import Image, ImageEnhance

    w, h = img.size
    if max(w, h) < 1200:
        scale = 1200 / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        logger.debug("업스케일 %.1fx → %dx%d", scale, *img.size)

    # 컬러 이미지 그대로 대비 강화 후 그레이스케일 변환
    img = ImageEnhance.Contrast(img).enhance(2.5)
    img = img.convert("L").convert("RGB")   # 그레이스케일 → RGB (EasyOCR 입력 형식 유지)
    return img


# ──────────────────────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────────────────────

def extract_image_with_regions(path: str | Path) -> Dict[str, Any]:
    """
    이미지 파일에서 OCR 텍스트와 바운딩 박스를 함께 추출한다.

    Args:
        path: 이미지 파일 경로 (PNG/JPG/JPEG/HEIC/WEBP)

    Returns:
        {
            "text":        str,           # 전체 OCR 텍스트 (줄 구분 \\n)
            "ocr_results": List[Tuple],   # [(bbox, text, conf), ...]
                                          # bbox = [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
            "source_path": str,           # 파일 절대 경로
            "page_number": int,           # 항상 1 (이미지는 단일 페이지)
        }
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"이미지 파일 없음: {path}")

    try:
        import easyocr
        import numpy as np
    except ImportError as exc:
        raise ImportError(f"OCR 의존성 누락: {exc}. pip install easyocr") from exc

    img = _load_image_pil(path)
    img = _preprocess_image(img)

    reader = easyocr.Reader(["en", "ko"], gpu=False, verbose=False)
    img_array = np.array(img)

    # detail=1 → [(bbox, text, confidence), ...]
    # bbox = [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
    ocr_results: List[Tuple] = reader.readtext(img_array, detail=1, paragraph=False)

    full_text = "\n".join(r[1] for r in ocr_results).strip()

    if len(full_text) < _MIN_TEXT_LENGTH:
        logger.warning("OCR 결과 매우 짧음 (%d자): %s", len(full_text), path.name)

    logger.info("이미지 OCR 완료: %s → %d자, %d 블록", path.name, len(full_text), len(ocr_results))

    return {
        "text":        full_text,
        "ocr_results": ocr_results,
        "source_path": str(path),
        "page_number": 1,
    }


def extract_image(path: str | Path) -> List[Tuple[int, str]]:
    """
    하위 호환 래퍼 — (page_number, text) 리스트 반환.
    바운딩 박스가 필요 없는 경우 사용.
    """
    result = extract_image_with_regions(path)
    return [(result["page_number"], result["text"])]


def map_pii_to_image_regions(
    ocr_results: List[Tuple],
    pii_findings: List[Any],
) -> List[List]:
    """
    PII findings (청크 내 char offset) 을 이미지 바운딩 박스로 변환한다.

    OCR 텍스트를 "\\n" 으로 이어 붙인 문자열 기준 오프셋과
    PII finding 의 start/end 를 비교하여 겹치는 OCR 블록을 찾아 반환.

    Args:
        ocr_results:  EasyOCR detail=1 결과 [(bbox, text, conf), ...]
        pii_findings: PIIFinding 리스트 (start, end 오프셋 포함)

    Returns:
        모자이크 처리할 bbox 목록 [[[x1,y1],[x2,y1],[x2,y2],[x1,y2]], ...]
    """
    if not pii_findings or not ocr_results:
        return []

    pii_bboxes: List[List] = []
    char_offset = 0

    for bbox, text, _conf in ocr_results:
        block_start = char_offset
        block_end   = char_offset + len(text)

        for finding in pii_findings:
            if finding.start < block_end and finding.end > block_start:
                pii_bboxes.append(bbox)
                break

        char_offset = block_end + 1  # +1 for \n separator

    return pii_bboxes
