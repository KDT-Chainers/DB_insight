"""
pdf_extractor.py
──────────────────────────────────────────────────────────────────────────────
PDF 텍스트 추출.

전략:
  1차: PyMuPDF(fitz) 로 직접 텍스트 추출
  2차: 텍스트가 거의 없으면(스캔 PDF) → EasyOCR 로 OCR 수행
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# OCR 임계값: 페이지당 평균 글자 수가 이 값 미만이면 OCR 수행
_OCR_THRESHOLD = 50


def extract_pdf(path: str | Path) -> List[Tuple[int, str]]:
    """
    PDF 파일에서 텍스트를 추출.

    Args:
        path: PDF 파일 경로

    Returns:
        List of (page_number, text) — 1-indexed
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF 파일 없음: {path}")

    pages = _extract_with_pymupdf(path)

    # 평균 텍스트 길이 계산
    total_chars = sum(len(t) for _, t in pages)
    avg_chars = total_chars / max(len(pages), 1)

    if avg_chars < _OCR_THRESHOLD:
        logger.info("텍스트 희박 (평균 %.1f 자) → OCR 수행: %s", avg_chars, path.name)
        pages = _extract_with_ocr(path)

    return pages


def extract_pdf_with_metadata(path: str | Path) -> List[Dict[str, Any]]:
    """
    PDF 텍스트와 위치 메타데이터(페이지 번호, bbox)를 함께 추출한다.
    원본 파일은 절대 수정하지 않는다.

    반환 형식:
        [
            {
                "text":        str,
                "page_number": int,               # 1-indexed
                "bbox":        dict | None,        # {"x": float, "y": float, "w": float, "h": float}
                "source_path": str                 # 파일 절대 경로
            },
            ...
        ]

    bbox는 각 페이지에서 추출된 텍스트 블록들의 전체 범위(bounding rect)다.
    추출 불가능한 경우(OCR 페이지 등) None으로 반환한다.
    """
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF 파일 없음: {path}")

    source_path = str(path)

    # 1차: PyMuPDF로 텍스트 + bbox 추출
    result = _extract_with_pymupdf_meta(path, source_path)

    # OCR 필요 여부 확인
    total_chars = sum(len(r["text"]) for r in result)
    avg_chars = total_chars / max(len(result), 1)
    if avg_chars < _OCR_THRESHOLD:
        logger.info("텍스트 희박 → OCR 수행 (bbox 없음): %s", path.name)
        # OCR 결과는 bbox 없이 반환
        ocr_pages = _extract_with_ocr(path)
        return [
            {"text": t, "page_number": n, "bbox": None, "source_path": source_path}
            for n, t in ocr_pages
        ]

    return result


def _extract_with_pymupdf_meta(path: Path, source_path: str) -> List[Dict[str, Any]]:
    """
    PyMuPDF로 페이지별 텍스트 블록과 bbox를 추출한다.
    각 페이지의 모든 텍스트 블록을 포함하는 bounding rect를 계산한다.
    """
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF 미설치 → bbox 없이 텍스트만 추출")
        pages = _extract_with_pdfminer(path)
        return [
            {"text": t, "page_number": n, "bbox": None, "source_path": source_path}
            for n, t in pages
        ]

    result: List[Dict[str, Any]] = []
    try:
        doc = fitz.open(str(path))
        for page_num, page in enumerate(doc, start=1):
            page_dict = page.get_text("dict")
            blocks = page_dict.get("blocks", [])

            text_parts: List[str] = []
            x0_list: List[float] = []
            y0_list: List[float] = []
            x1_list: List[float] = []
            y1_list: List[float] = []

            for block in blocks:
                if block.get("type") != 0:  # type 0 = text block
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        span_text = span.get("text", "").strip()
                        if span_text:
                            text_parts.append(span_text)
                bx0, by0, bx1, by1 = block.get("bbox", (0, 0, 0, 0))
                if bx1 > bx0 and by1 > by0:
                    x0_list.append(bx0)
                    y0_list.append(by0)
                    x1_list.append(bx1)
                    y1_list.append(by1)

            text = " ".join(text_parts).strip()
            if not text:
                text = page.get_text("text").strip()

            bbox: Optional[Dict[str, Any]] = None
            if x0_list:
                bbox = {
                    "x": min(x0_list),
                    "y": min(y0_list),
                    "w": max(x1_list) - min(x0_list),
                    "h": max(y1_list) - min(y0_list),
                }

            result.append({
                "text":        text,
                "page_number": page_num,
                "bbox":        bbox,
                "source_path": source_path,
            })
        doc.close()
    except Exception as exc:
        logger.error("PyMuPDF 메타 추출 오류: %s", exc)
        pages = _extract_with_pdfminer(path)
        return [
            {"text": t, "page_number": n, "bbox": None, "source_path": source_path}
            for n, t in pages
        ]

    return result


# ── 1차: PyMuPDF ──────────────────────────────────────────────────────────────

def _extract_with_pymupdf(path: Path) -> List[Tuple[int, str]]:
    """PyMuPDF 로 텍스트 레이어 추출"""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("PyMuPDF(fitz) 미설치 → pdfminer 폴백")
        return _extract_with_pdfminer(path)

    pages: List[Tuple[int, str]] = []
    try:
        doc = fitz.open(str(path))
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text")
            pages.append((page_num, text.strip()))
        doc.close()
    except Exception as exc:
        logger.error("PyMuPDF 오류: %s", exc)
        return _extract_with_pdfminer(path)

    return pages


def _extract_with_pdfminer(path: Path) -> List[Tuple[int, str]]:
    """pdfminer.six 폴백 추출"""
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextContainer
    except ImportError:
        logger.error("pdfminer.six 미설치")
        return []

    pages: List[Tuple[int, str]] = []
    try:
        for page_num, page_layout in enumerate(extract_pages(str(path)), start=1):
            texts = []
            for element in page_layout:
                if isinstance(element, LTTextContainer):
                    texts.append(element.get_text())
            pages.append((page_num, "".join(texts).strip()))
    except Exception as exc:
        logger.error("pdfminer 오류: %s", exc)

    return pages


# ── 2차: OCR ─────────────────────────────────────────────────────────────────

def _extract_with_ocr(path: Path) -> List[Tuple[int, str]]:
    """
    EasyOCR 로 각 페이지를 이미지로 렌더링 후 OCR.
    PyMuPDF 로 렌더링, EasyOCR 로 인식.
    """
    try:
        import fitz
        import easyocr
    except ImportError as exc:
        logger.error("OCR 의존성 누락: %s", exc)
        return []

    reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
    pages: List[Tuple[int, str]] = []

    try:
        doc = fitz.open(str(path))
        for page_num, page in enumerate(doc, start=1):
            # 150dpi 로 렌더링
            mat = fitz.Matrix(150 / 72, 150 / 72)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")

            results = reader.readtext(img_bytes, detail=0, paragraph=True)
            text = "\n".join(results)
            pages.append((page_num, text.strip()))
        doc.close()
    except Exception as exc:
        logger.error("OCR 처리 오류: %s", exc)

    return pages
