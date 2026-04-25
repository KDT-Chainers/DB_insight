"""
문서 임베더 (PDF, DOCX, TXT, HWP, PPTX, XLSX)

파이프라인:
  1. 파일 형식 감지
  2. 텍스트 추출          ← TODO: 각 형식별 구현
  3. 청킹 (base.make_chunks)
  4. 임베딩 (base.encode_texts)
  5. ChromaDB 저장 (vector_store.upsert_chunks)
"""

from __future__ import annotations

import hashlib
import os

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
    ".odt", ".odp", ".ods", ".rtf",
    ".hwp", ".hwpx",
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv",
    ".html", ".htm", ".epub",
}


# ── 텍스트 추출 ───────────────────────────────────────────────────

def _extract_text(file_path: str) -> str:
    """파일에서 원시 텍스트를 추출해 반환."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".txt":
        # TXT: 직접 읽기
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    if ext == ".pdf":
        # TODO: pdfplumber 또는 PyMuPDF 로 텍스트 추출
        # import pdfplumber
        # with pdfplumber.open(file_path) as pdf:
        #     return "\n".join(page.extract_text() or "" for page in pdf.pages)
        raise NotImplementedError("PDF 추출 미구현")

    if ext == ".docx":
        # TODO: python-docx 로 텍스트 추출
        # import docx
        # doc = docx.Document(file_path)
        # return "\n".join(p.text for p in doc.paragraphs)
        raise NotImplementedError("DOCX 추출 미구현")

    if ext == ".hwp":
        # TODO: hwp 파싱 (olefile 또는 pyhwp)
        raise NotImplementedError("HWP 추출 미구현")

    if ext == ".pptx":
        # TODO: python-pptx 로 슬라이드 텍스트 추출
        # from pptx import Presentation
        # prs = Presentation(file_path)
        # texts = []
        # for slide in prs.slides:
        #     for shape in slide.shapes:
        #         if shape.has_text_frame:
        #             texts.append(shape.text_frame.text)
        # return "\n".join(texts)
        raise NotImplementedError("PPTX 추출 미구현")

    if ext == ".xlsx":
        # TODO: openpyxl 로 셀 텍스트 추출
        # import openpyxl
        # wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        # rows = []
        # for ws in wb.worksheets:
        #     for row in ws.iter_rows(values_only=True):
        #         rows.append(" ".join(str(c) for c in row if c is not None))
        # return "\n".join(rows)
        raise NotImplementedError("XLSX 추출 미구현")

    raise ValueError(f"지원하지 않는 확장자: {ext}")


# ── 진입점 ────────────────────────────────────────────────────────

def embed(file_path: str) -> dict:
    """
    문서 파일을 임베딩하여 벡터 저장소에 저장.

    반환:
      {"status": "done",    "chunks": int}
      {"status": "skipped", "reason": str}
      {"status": "error",   "reason": str}
    """
    from embedders.base import make_chunks, encode_texts
    from db.vector_store import upsert_chunks, delete_file

    try:
        # 1. 텍스트 추출
        text = _extract_text(file_path)
    except NotImplementedError as e:
        return {"status": "skipped", "reason": str(e)}
    except Exception as e:
        return {"status": "error", "reason": f"텍스트 추출 실패: {e}"}

    if not text.strip():
        return {"status": "skipped", "reason": "텍스트 없음"}

    try:
        # 2. 청킹
        chunks = make_chunks(text)

        # 3. 임베딩
        vectors = encode_texts(chunks)

        # 4. 저장 (기존 청크 먼저 삭제 → 재인덱싱 지원)
        delete_file(file_path)

        file_name = os.path.basename(file_path)
        file_hash = hashlib.md5(file_path.encode()).hexdigest()[:8]

        ids       = [f"{file_hash}_doc_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "file_path":   file_path,
                "file_name":   file_name,
                "file_type":   "doc",
                "chunk_index": i,
                "chunk_text":  chunk[:300],
            }
            for i, chunk in enumerate(chunks)
        ]

        upsert_chunks(ids=ids, embeddings=vectors, metadatas=metadatas)

        return {"status": "done", "chunks": len(chunks)}

    except Exception as e:
        return {"status": "error", "reason": str(e)}
