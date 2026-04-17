"""
음성 임베더 (MP3, WAV, M4A 등)

담당: 음성 팀원
입력: file_path (절대 경로)
출력: {"status": "done"} | {"status": "skipped"} | {"status": "error", "reason": str}
"""


SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def embed(file_path: str) -> dict:
    # TODO: STT → chunking → 임베딩 → ChromaDB 저장
    return {"status": "skipped", "reason": "Not implemented"}
