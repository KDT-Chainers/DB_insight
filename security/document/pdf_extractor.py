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
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 텍스트 정제 ───────────────────────────────────────────────────────────────

# ── JS/코드 오염 패턴 ─────────────────────────────────────────────────────────
_NOISE_PATTERNS: List[re.Pattern] = [re.compile(p) for p in [
    r'\.[a-zA-Z_$][a-zA-Z0-9_$]*\s*\(',            # .toObject( .textContent( 등 메서드 호출
    r'\b(?:function|var|let|const|return|typeof)\b', # JS 예약어
    r'[a-zA-Z_$][a-zA-Z0-9_$]*\.[a-zA-Z_$][a-zA-Z0-9_$]*\.[a-zA-Z_$]',  # a.b.c 체인
    r'<[a-zA-Z][^>]{0,80}>',                        # HTML 태그
    r'\\u[0-9a-fA-F]{4}',                           # \uXXXX 유니코드 이스케이프
]]

# ── Jamo / 혼합 스크립트 노이즈 패턴 ─────────────────────────────────────────
# PDF 폰트 인코딩 오류로 한글 자모가 분해돼 들어오는 경우
#   예: "역ᄉ Hàn 숨 프ung ᄒᆞᆫ ᄀᆞ皖"
_JAMO_RE = re.compile(
    r'[\u1100-\u11FF'   # Hangul Jamo (초·중·종성 낱자)
    r'\uA960-\uA97F'    # Hangul Jamo Extended-A
    r'\uD7B0-\uD7FF]'   # Hangul Jamo Extended-B
)
# CJK 한자 (중국어/일본어 상용 범위)
_CJK_RE = re.compile(r'[\u4E00-\u9FFF\u3400-\u4DBF\uF900-\uFAFF]')
# 완성형 한글 음절
_SYLLABLE_RE = re.compile(r'[\uAC00-\uD7A3]')
# 스크립트 전환 카운터: 짧은 구간에 서로 다른 문자계가 번갈아 나타나는지 탐지
_SCRIPT_SWITCH_RE = re.compile(
    r'(?:[\uAC00-\uD7A3]+[A-Za-z\u4E00-\u9FFF]+|'
    r'[A-Za-z\u4E00-\u9FFF]+[\uAC00-\uD7A3]+)'
    r'(?:[A-Za-z\u4E00-\u9FFF]+[\uAC00-\uD7A3]+|'
    r'[\uAC00-\uD7A3]+[A-Za-z\u4E00-\u9FFF]+){2,}'
)

_EXCESS_WHITESPACE_RE = re.compile(r'\n{3,}')


def _is_garbled_line(stripped: str) -> bool:
    """
    PDF 폰트 인코딩 오류로 생긴 깨진 줄 여부 판별.

    판별 기준 (하나라도 해당하면 True):
      1. 분해 자모(Jamo) 비율 ≥ 8% — "ᄒᆞᆫ ᄀᆞ" 같은 노이즈
      2. 한자 비율이 완성 한글 비율을 초과하고 한자가 3자 이상
      3. 짧은 구간에 3회 이상 스크립트 전환 (한글↔영문↔한자 섞임)
    """
    n = len(stripped)
    if n == 0:
        return False
    jamo_cnt = len(_JAMO_RE.findall(stripped))
    if jamo_cnt >= 2 and jamo_cnt / n >= 0.08:
        return True
    cjk_cnt = len(_CJK_RE.findall(stripped))
    syl_cnt = len(_SYLLABLE_RE.findall(stripped))
    if cjk_cnt >= 3 and cjk_cnt > syl_cnt:
        return True
    if _SCRIPT_SWITCH_RE.search(stripped):
        return True
    return False


def _clean_text(text: str) -> str:
    """PDF 추출 텍스트에서 JS/HTML 코드 오염 및 폰트 인코딩 노이즈를 제거한다."""
    if not text:
        return text
    lines = text.splitlines()
    clean_lines: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            clean_lines.append("")
            continue
        # JS/코드 패턴 2개 이상 → 제거
        hit = sum(1 for p in _NOISE_PATTERNS if p.search(stripped))
        if hit >= 2:
            logger.debug("[pdf_cleaner] JS 노이즈 줄 제거: %r", stripped[:60])
            continue
        # Jamo/혼합 스크립트 깨진 줄 → 제거
        if _is_garbled_line(stripped):
            logger.debug("[pdf_cleaner] 깨진 줄 제거: %r", stripped[:60])
            continue
        clean_lines.append(line)
    result = "\n".join(clean_lines)
    result = _EXCESS_WHITESPACE_RE.sub("\n\n", result)
    return result.strip()

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

            text = _clean_text(" ".join(text_parts))
            if not text:
                text = _clean_text(page.get_text("text"))

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
            pages.append((page_num, _clean_text(text)))
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
            pages.append((page_num, _clean_text("".join(texts))))
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
