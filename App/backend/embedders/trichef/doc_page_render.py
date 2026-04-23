"""embedders/trichef/doc_page_render.py — PDF/DOCX → JPEG 페이지 이미지."""
from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF

from config import PATHS

logger = logging.getLogger(__name__)
PAGE_DIR = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "page_images"


def _sanitize(name: str) -> str:
    """Windows 경로 금지·공백 정제."""
    bad = '<>:"/\\|?*'
    s = "".join("_" if c in bad else c for c in name).strip().rstrip(".")
    return s or "unnamed"


def render_pdf(pdf_path: Path, dpi: int = 110) -> list[Path]:
    """PDF 의 각 페이지를 JPEG 로 저장. 리턴: [페이지 이미지 경로...]"""
    doc_id = _sanitize(pdf_path.stem)
    out_dir = PAGE_DIR / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    try:
        if pdf_path.stat().st_size == 0:
            logger.warning(f"[render_pdf] 빈 파일 스킵: {pdf_path.name}")
            return results
    except OSError as e:
        logger.warning(f"[render_pdf] stat 실패 {pdf_path.name}: {e}")
        return results
    try:
        d_ctx = fitz.open(pdf_path)
    except Exception as e:
        logger.warning(f"[render_pdf] open 실패 {pdf_path.name}: {e}")
        return results
    with d_ctx as d:
        for i, page in enumerate(d):
            out = out_dir / f"p{i:04d}.jpg"
            if out.exists():
                results.append(out)
                continue
            pix = page.get_pixmap(dpi=dpi)
            pix.save(out)
            results.append(out)
    logger.info(f"[render_pdf] {pdf_path.name} → {len(results)}장")
    return results
