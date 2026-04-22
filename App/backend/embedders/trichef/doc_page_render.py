"""embedders/trichef/doc_page_render.py — PDF/DOCX → JPEG 페이지 이미지."""
from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF

from config import PATHS

logger = logging.getLogger(__name__)
PAGE_DIR = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "page_images"


def render_pdf(pdf_path: Path, dpi: int = 110) -> list[Path]:
    """PDF 의 각 페이지를 JPEG 로 저장. 리턴: [페이지 이미지 경로...]"""
    doc_id = pdf_path.stem
    out_dir = PAGE_DIR / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    with fitz.open(pdf_path) as d:
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
