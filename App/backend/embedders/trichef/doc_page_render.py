"""embedders/trichef/doc_page_render.py — PDF/DOCX → JPEG 페이지 이미지."""
from __future__ import annotations

import hashlib
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


def stem_key_for(rel_key: str) -> str:
    """registry key(raw_DB 기준 상대경로) → 고유 stem.

    형식: `{sanitized_stem}__{md5(rel_key)[:8]}`.
    서로 다른 디렉토리의 동일 파일명 충돌을 방지한다.
    """
    stem = _sanitize(Path(rel_key).stem)
    h = hashlib.md5(rel_key.encode("utf-8")).hexdigest()[:8]
    return f"{stem}__{h}"


def render_pdf(pdf_path: Path, dpi: int = 110,
               stem_key: str | None = None) -> list[Path]:
    """PDF 의 각 페이지를 JPEG 로 저장. 리턴: [페이지 이미지 경로...].

    `stem_key` 가 주어지면 `PAGE_DIR/<stem_key>/p####.jpg` 로 저장하여
    동일 stem 충돌을 구조적으로 방지한다. 레거시 호출(stem_key=None)은
    `_sanitize(pdf_path.stem)` 으로 폴백.
    """
    doc_id = stem_key or _sanitize(pdf_path.stem)
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
