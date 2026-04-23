"""
음악/음성 파일 임베더 (MP3, WAV, M4A, AAC, FLAC, OGG, WMA)

파이프라인:
  1. librosa로 오디오 로드 (최대 90초)
  2. 믹스 특징 추출 (tempo, MFCC, chroma, spectral)
  3. HPSS 보컬 분리 → 보컬 특징 추출
  4. features_to_tags() → 자연어 태그 문자열 (한·영 혼합)
  5. 파일명 파싱 → 아티스트/곡명 힌트 보강
  6. ko-sroberta 768d 임베딩
  7. ChromaDB "files_audio" 컬렉션 저장

캐시:
  extracted_DB/Rec/{stem}_tags.txt   ← 태그 텍스트 (재인덱싱 시 재사용)

검색:
  encode_query_ko(query) → 768d → files_audio 컬렉션 유사도 검색
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"}

# ── 캐시 경로 ────────────────────────────────────────────────────────
from config import EXTRACTED_DB_AUDIO as _CACHE_DIR


def _cache_path(file_path: str) -> Path:
    """STT·태그 캐시 경로 (extracted_DB/Rec/{name}_{hash}_tags.txt)"""
    h = hashlib.md5(file_path.encode()).hexdigest()[:12]
    name = Path(file_path).stem
    return _CACHE_DIR / f"{name}_{h}_tags.txt"


# ── 파일명 파싱 (아티스트/곡명 힌트) ────────────────────────────────

_SEP_PATTERN = re.compile(r"\s*[-–—_]\s*")


def _parse_filename(file_path: str) -> tuple[str, str]:
    """
    파일명에서 아티스트 / 곡명 추측.
    "아티스트 - 곡명.mp3" 또는 "아티스트 _ 곡명.mp3" 형식 지원.
    반환: (artist, title)
    """
    stem = Path(file_path).stem
    # 숫자 인덱스 제거 (예: "01. 곡명")
    stem = re.sub(r"^\d+[.\s]+", "", stem).strip()
    parts = _SEP_PATTERN.split(stem, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", stem.strip()


def _build_text(tags: str, artist: str, title: str) -> str:
    """태그 + 아티스트/곡명을 합쳐 임베딩용 최종 텍스트 구성."""
    parts = [tags]
    if title:
        parts.append(f"곡명 {title} song title {title}")
    if artist:
        parts.append(f"가수 {artist} artist {artist}")
    return " ".join(parts)


# ── 진입점 ──────────────────────────────────────────────────────────

def embed(file_path: str) -> dict:
    """
    음악 파일 한 개를 임베딩하여 ChromaDB에 저장.

    반환:
      {"status": "done",    "chunks": 1}
      {"status": "skipped", "reason": str}
      {"status": "error",   "reason": str}
    """
    from embedders.base import encode_texts_ko
    from db.vector_store import upsert_chunks, delete_file

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return {"status": "skipped", "reason": f"지원하지 않는 확장자: {ext}"}

    if not os.path.isfile(file_path):
        return {"status": "skipped", "reason": "파일이 존재하지 않습니다"}

    # 1. 캐시 확인
    cache = _cache_path(file_path)
    artist, title = _parse_filename(file_path)

    if cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            tags_text = cached.get("tags", "")
        except Exception:
            tags_text = cache.read_text(encoding="utf-8")
    else:
        # 2. librosa 특징 추출 → 텍스트 태그 생성
        try:
            import librosa  # noqa: import check
        except ImportError:
            return {"status": "error", "reason": "librosa가 설치되지 않았습니다. pip install librosa"}

        try:
            from music_features.audio_features import extract_all
            from music_features.textify import features_to_tags

            out = extract_all(file_path, cache_dir=_CACHE_DIR)
            flat = {**out["flat_mix"], **out["flat_vocal"]}
            tags_text = features_to_tags(flat)

            # 캐시 저장
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(
                json.dumps({"tags": tags_text, "artist": artist, "title": title},
                           ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            return {"status": "error", "reason": f"오디오 특징 추출 실패: {e}"}

    if not tags_text.strip():
        return {"status": "skipped", "reason": "태그 텍스트 생성 실패"}

    # 3. 최종 임베딩 텍스트 구성 (태그 + 아티스트/곡명)
    embed_text = _build_text(tags_text, artist, title)

    try:
        # 4. ko-sroberta 768d 임베딩
        vectors = encode_texts_ko([embed_text])

        # 5. 기존 청크 삭제 후 upsert
        delete_file(file_path, file_type="audio")

        file_name = os.path.basename(file_path)
        file_hash = hashlib.md5(file_path.encode()).hexdigest()[:8]

        # chunk_text에 아티스트/곡명 힌트 포함 (snippet에 표시됨)
        hint_text = ""
        if title:
            hint_text += f" 곡명: {title}"
        if artist:
            hint_text += f" 아티스트: {artist}"
        chunk_text = (tags_text + hint_text).strip()[:300]

        ids = [f"{file_hash}_aud_0"]
        metadatas = [
            {
                "file_path":   file_path,
                "file_name":   file_name,
                "file_type":   "audio",
                "folder_path": str(Path(file_path).parent),
                "chunk_index": 0,
                "chunk_text":  chunk_text,
            }
        ]

        upsert_chunks(ids=ids, embeddings=vectors, metadatas=metadatas)
        return {"status": "done", "chunks": 1}

    except Exception as e:
        return {"status": "error", "reason": str(e)}
