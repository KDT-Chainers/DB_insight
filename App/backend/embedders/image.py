"""
이미지 임베더 (JPG, PNG, WEBP 등)

담당: 이미지 팀원
입력: file_path (절대 경로)
출력: {"status": "done"} | {"status": "skipped"} | {"status": "error", "reason": str}
"""


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}


def embed(file_path: str) -> dict:
    # TODO: OCR / 캡션 생성 → chunking → 임베딩 → ChromaDB 저장
    return {"status": "skipped", "reason": "Not implemented"}
