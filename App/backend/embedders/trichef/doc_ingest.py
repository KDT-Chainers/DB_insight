"""embedders/trichef/doc_ingest.py — 문서 확장자 통합 → 페이지 이미지 (v2 P1).

지원 체계:
  .pdf                        PyMuPDF 직접 렌더
  .docx .pptx .xlsx           python-docx/pptx/openpyxl → 변환 (LibreOffice 선호)
  .doc .ppt .xls              LibreOffice 필수
  .hwp .hwpx                  LibreOffice 필수 (H2Orestart 확장 권장)
  .csv                        pandas → 페이지 분할 텍스트
  .html .htm                  BeautifulSoup → 텍스트
  .txt .md                    원문 → 페이지 분할 텍스트

LibreOffice 미설치 시 office/hwp 계열은 skip 후 경고.
텍스트/CSV/HTML 은 페이지 이미지 없이 '가상 페이지' — Re/Z 축은 zero-vec, Im 축만 사용.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from config import PATHS

from embedders.trichef import doc_page_render

logger = logging.getLogger(__name__)


OFFICE_EXT = {".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
              ".odt", ".odp", ".ods", ".rtf"}
HWP_EXT    = {".hwp", ".hwpx"}
TEXT_EXT   = {".txt", ".md", ".markdown", ".rst", ".log"}
STRUCT_EXT = {".csv", ".tsv", ".json", ".html", ".htm", ".xml"}

SOFFICE_CANDIDATES = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
]


def _find_soffice() -> str | None:
    for p in SOFFICE_CANDIDATES:
        if Path(p).exists():
            return p
    if shutil.which("soffice"):
        return shutil.which("soffice")
    return None


def _libreoffice_to_pdf(src: Path, out_dir: Path) -> Path | None:
    sof = _find_soffice()
    if not sof:
        logger.warning(f"[doc_ingest] LibreOffice 미설치 — {src.name} 스킵")
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [sof, "--headless", "--convert-to", "pdf",
             "--outdir", str(out_dir), str(src)],
            check=True, capture_output=True, timeout=180,
        )
    except Exception as e:
        logger.exception(f"[doc_ingest] LO 변환 실패 {src.name}: {e}")
        return None
    pdf = out_dir / (src.stem + ".pdf")
    return pdf if pdf.exists() else None


def to_pages(src: Path, stem_key: str | None = None) -> list[Path]:
    """모든 지원 포맷 → 페이지 JPEG 리스트.

    `stem_key` 가 주어지면 render_pdf 로 그대로 전달되어 PAGE_DIR 의 서브
    디렉토리 이름이 충돌 방지 형식(`<stem>__<md5hash>`)으로 생성된다.
    """
    ext = src.suffix.lower()

    if ext == ".pdf":
        return doc_page_render.render_pdf(src, stem_key=stem_key)

    if ext in OFFICE_EXT or ext in HWP_EXT:
        with tempfile.TemporaryDirectory() as td:
            pdf = _libreoffice_to_pdf(src, Path(td))
            if pdf is None:
                return []
            # stem 충돌 방지: 원본 절대경로 해시 기반 서브디렉토리 사용
            import hashlib
            sub = hashlib.md5(str(src.resolve()).encode("utf-8")).hexdigest()[:8]
            pdf_cache = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "converted_pdf" / sub
            pdf_cache.mkdir(parents=True, exist_ok=True)
            final = pdf_cache / pdf.name
            shutil.copy2(pdf, final)
            return doc_page_render.render_pdf(final, stem_key=stem_key)

    if ext in TEXT_EXT:
        return _virtual_text_pages(src.read_text(encoding="utf-8", errors="ignore"),
                                    src.stem)
    if ext == ".csv":
        try:
            import pandas as pd
            df = pd.read_csv(src, dtype=str, keep_default_na=False)
            return _virtual_text_pages(df.to_string(index=False), src.stem)
        except Exception as e:
            logger.exception(f"[doc_ingest] csv 실패 {src}: {e}")
            return []
    if ext in {".html", ".htm"}:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(src.read_bytes(), "html.parser")
            return _virtual_text_pages(soup.get_text("\n", strip=True), src.stem)
        except Exception as e:
            logger.exception(f"[doc_ingest] html 실패 {src}: {e}")
            return []

    logger.debug(f"[doc_ingest] 미지원 확장자: {ext}")
    return []


def converted_pdf_path(src: Path) -> Path | None:
    """doc_ingest 변환본 경로. 신규 규칙(해시 서브디렉토리) 우선, 없으면 레거시 위치 fallback."""
    import hashlib
    conv_root = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "converted_pdf"
    sub = hashlib.md5(str(src.resolve()).encode("utf-8")).hexdigest()[:8]
    new_path = conv_root / sub / f"{src.stem}.pdf"
    if new_path.exists():
        return new_path
    legacy = conv_root / f"{src.stem}.pdf"
    if legacy.exists():
        return legacy
    return None


def _virtual_text_pages(text: str, stem: str, chars_per_page: int = 1500) -> list[Path]:
    """텍스트 → 가상 페이지 (이미지 없음 → 검색 도메인 `doc_text` 전용)."""
    out_dir = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "text_pages" / doc_page_render._sanitize(stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages: list[Path] = []
    chunks = [text[i:i+chars_per_page] for i in range(0, len(text), chars_per_page)] or [""]
    for i, chunk in enumerate(chunks):
        p = out_dir / f"p{i:04d}.txt"
        if not p.exists():
            p.write_text(chunk, encoding="utf-8")
        pages.append(p)
    return pages
