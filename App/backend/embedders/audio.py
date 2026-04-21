"""
음성 임베더 (MP3, WAV, M4A, AAC, FLAC, OGG)

파이프라인:
  1. 음성 파일 로드
  2. STT (Speech-to-Text) → 전사 텍스트   ← TODO: Whisper 또는 다른 방식 구현
  3. 청킹 (base.make_chunks)
  4. 임베딩 (base.encode_texts)
  5. ChromaDB 저장 (vector_store.upsert_chunks)
"""

from __future__ import annotations

import hashlib
import os

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

# ── 캐시 경로 ─────────────────────────────────────────────────────
# STT 결과를 extracted_DB 에 .txt 로 캐싱 (재인덱싱 시 STT 재실행 방지)
from config import EXTRACTED_DB


def _cache_path(file_path: str) -> "Path":
    """원본 파일 경로 → STT 캐시 .txt 경로 (extracted_DB/<hash>_stt.txt)"""
    import hashlib
    from pathlib import Path
    h = hashlib.md5(file_path.encode()).hexdigest()[:12]
    name = Path(file_path).stem
    return EXTRACTED_DB / f"{name}_{h}_stt.txt"


# ── STT ───────────────────────────────────────────────────────────

def _transcribe(file_path: str) -> str:
    """
    음성 파일 → 전사 텍스트 반환.

    TODO: 원하는 STT 방식으로 구현
    예시 A) faster-whisper (GPU 추천)
      from faster_whisper import WhisperModel
      model = WhisperModel("medium", device="cuda", compute_type="float16")
      segments, _ = model.transcribe(file_path, language="ko")
      return " ".join(seg.text for seg in segments)

    예시 B) openai-whisper (CPU 호환)
      import whisper
      model = whisper.load_model("base")
      result = model.transcribe(file_path, language="ko")
      return result["text"]

    예시 C) 외부 API (OpenAI, Clova 등)
    """
    raise NotImplementedError("STT 미구현")


# ── 진입점 ────────────────────────────────────────────────────────

def embed(file_path: str) -> dict:
    """
    음성 파일을 임베딩하여 벡터 저장소에 저장.

    반환:
      {"status": "done",    "chunks": int}
      {"status": "skipped", "reason": str}
      {"status": "error",   "reason": str}
    """
    from embedders.base import make_chunks, encode_texts
    from db.vector_store import upsert_chunks, delete_file

    # 캐시된 STT 결과가 있으면 재사용
    cache = _cache_path(file_path)
    if cache.exists():
        text = cache.read_text(encoding="utf-8")
    else:
        try:
            # 1. STT → 텍스트
            text = _transcribe(file_path)
            # 캐시에 저장
            cache.write_text(text, encoding="utf-8")
        except NotImplementedError as e:
            return {"status": "skipped", "reason": str(e)}
        except Exception as e:
            return {"status": "error", "reason": f"STT 실패: {e}"}

    if not text.strip():
        return {"status": "skipped", "reason": "텍스트 없음"}

    try:
        # 2. 청킹
        chunks = make_chunks(text)

        # 3. 임베딩
        vectors = encode_texts(chunks)

        # 4. 저장
        delete_file(file_path)

        file_name = os.path.basename(file_path)
        file_hash = hashlib.md5(file_path.encode()).hexdigest()[:8]

        ids       = [f"{file_hash}_aud_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "file_path":   file_path,
                "file_name":   file_name,
                "file_type":   "audio",
                "chunk_index": i,
                "chunk_text":  chunk[:300],
            }
            for i, chunk in enumerate(chunks)
        ]

        upsert_chunks(ids=ids, embeddings=vectors, metadatas=metadatas)

        return {"status": "done", "chunks": len(chunks)}

    except Exception as e:
        return {"status": "error", "reason": str(e)}
