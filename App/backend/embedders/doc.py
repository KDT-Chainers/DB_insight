"""
문서 임베더 (PDF, DOCX, TXT 등)

담당: 문서 팀원
입력: file_path (절대 경로)
출력: {"status": "done"} | {"status": "skipped"} | {"status": "error", "reason": str}
"""


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".hwp", ".pptx", ".xlsx"}


def embed(file_path: str) -> dict:
    # TODO: 문서 텍스트 추출 → chunking → 임베딩 → ChromaDB 저장
    return {"status": "skipped", "reason": "Not implemented"}
