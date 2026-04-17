"""
영상 임베더 (MP4, AVI, MOV 등)

담당: 영상 팀원
입력: file_path (절대 경로)
출력: {"status": "done"} | {"status": "skipped"} | {"status": "error", "reason": str}
"""


SUPPORTED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".wmv"}


def embed(file_path: str) -> dict:
    # TODO: 오디오 추출 → STT → chunking → 임베딩 → ChromaDB 저장
    return {"status": "skipped", "reason": "Not implemented"}
