"""[P4] PDF 내부 figure(이미지 객체) 추출 모듈.

PDF 페이지에 임베드된 이미지를 개별 figure 로 추출해, 도표/사진/다이어그램을
독립 검색 단위로 만들기 위한 전처리.

특징:
  - PyMuPDF (fitz) 의 page.get_images() + extract_image() 사용
  - 크기 필터: max(W, H) < 100px → 장식·icon 으로 간주, 폐기
  - 종횡비 필터: aspect > 12 → 가로/세로선 등 장식 폐기
  - SHA-256 dedup: 같은 이미지(로고 등)가 모든 페이지에 반복돼도 1회만 저장
  - 추출 결과 디스크 위치: Data/extracted_DB/Doc/figures/<doc_stem>/p<page>_f<idx>.<ext>

키 포맷 (Img 도메인 등록 시):
  doc_figures/<doc_stem>/p<page>_f<idx>.<ext>
  → 일반 staged/ 이미지와 prefix 로 구분, 검색 UI 에서 "도표" 뱃지 표시 가능
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


@dataclass
class ExtractedFigure:
    """추출된 figure 메타데이터."""
    src_pdf: Path        # 원본 PDF 경로
    page_idx: int        # 0-based 페이지 인덱스
    fig_idx: int         # 페이지 내 figure 순번 (0-based)
    out_path: Path       # 저장된 디스크 경로
    width: int
    height: int
    ext: str             # 'png', 'jpeg', ...
    sha8: str            # SHA-256 앞 8자 (dedup 키)
    rel_key: str         # Img 도메인 등록용 상대 key


def _doc_stem(pdf_path: Path) -> str:
    """문서 식별용 stem — 같은 stem 다른 폴더 충돌 방지 위해 hash 부착."""
    h = hashlib.md5(str(pdf_path.resolve()).encode("utf-8")).hexdigest()[:8]
    safe = pdf_path.stem.replace("\\", "_").replace("/", "_")
    return f"{safe}__{h}"


def extract_figures(
    pdf_path: Path,
    out_root: Path,
    *,
    min_side: int = 100,
    max_aspect: float = 12.0,
    skip_duplicates: bool = True,
) -> list[ExtractedFigure]:
    """PDF 한 건에서 figure 들을 추출해 디스크에 저장.

    Args:
        pdf_path: 원본 PDF
        out_root: 추출 결과 루트 (예: extracted_DB/Doc/figures)
        min_side: max(W, H) < min_side 이면 폐기 (장식·icon)
        max_aspect: max(W,H) / min(W,H) > max_aspect 이면 폐기 (가로/세로선)
        skip_duplicates: 같은 SHA 이미지는 1회만 저장 (로고·헤더 반복 제거)

    Returns:
        추출된 ExtractedFigure 리스트
    """
    import fitz  # PyMuPDF — 지연 import (서버 시작 시 비용 회피)

    if not pdf_path.is_file():
        return []
    stem = _doc_stem(pdf_path)
    out_dir = out_root / stem
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[ExtractedFigure] = []
    seen_shas: set[str] = set()

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        logger.warning(f"[pdf_figure] open 실패 {pdf_path.name}: {type(e).__name__}: {e}")
        return []

    try:
        for page_idx in range(doc.page_count):
            try:
                imgs = doc[page_idx].get_images(full=True)
            except Exception:
                continue
            for fig_idx, img in enumerate(imgs):
                xref = img[0]
                try:
                    info = doc.extract_image(xref)
                except Exception:
                    continue
                w = info.get("width", 0)
                h = info.get("height", 0)
                ext = info.get("ext", "png")
                data = info.get("image")
                if not data or w == 0 or h == 0:
                    continue
                # 크기 필터
                if max(w, h) < min_side:
                    continue
                # 종횡비 필터 (가로/세로 1자 line 제거)
                ar = max(w, h) / max(min(w, h), 1)
                if ar > max_aspect:
                    continue
                # SHA dedup
                sha = hashlib.sha256(data).hexdigest()
                sha8 = sha[:8]
                if skip_duplicates and sha in seen_shas:
                    continue
                seen_shas.add(sha)

                # 저장
                fname = f"p{page_idx:04d}_f{fig_idx:02d}_{sha8}.{ext}"
                fpath = out_dir / fname
                if not fpath.exists():
                    try:
                        fpath.write_bytes(data)
                    except Exception as e:
                        logger.warning(
                            f"[pdf_figure] 저장 실패 {fname}: {type(e).__name__}: {e}"
                        )
                        continue

                rel_key = f"doc_figures/{stem}/{fname}"
                results.append(ExtractedFigure(
                    src_pdf=pdf_path,
                    page_idx=page_idx,
                    fig_idx=fig_idx,
                    out_path=fpath,
                    width=w, height=h, ext=ext,
                    sha8=sha8, rel_key=rel_key,
                ))
    finally:
        doc.close()

    return results


def iter_pdf_files_in_doc_domain(raw_doc_dir: Path) -> Iterator[Path]:
    """raw_DB/Doc 하위의 모든 .pdf 파일 순회 (재귀)."""
    for p in raw_doc_dir.rglob("*.pdf"):
        if p.is_file():
            yield p
