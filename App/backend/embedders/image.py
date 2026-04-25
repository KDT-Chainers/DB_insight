"""
이미지 임베더 (JPG, PNG, WEBP, BMP, GIF, TIFF)

파이프라인:
  1. 이미지 로드
  2. 캡션 생성 (시각적 설명 텍스트)   ← TODO: BLIP 또는 다른 방식 구현
  3. 청킹 (짧으면 1청크)
  4. 임베딩 (base.encode_texts)
  5. ChromaDB 저장 (vector_store.upsert_chunks)
"""

from __future__ import annotations

import hashlib
import os

# HEIC/HEIF/AVIF 지원 (PIL plugin 자동 등록)
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass  # .heic/.heif 파일은 skip, 다른 포맷은 정상 동작
try:
    import pillow_avif  # noqa: F401  # plugin 자동 등록
except ImportError:
    pass

from _extensions import IMG_EXTS as _IMG_EXTS
SUPPORTED_EXTENSIONS = set(_IMG_EXTS)

# ── 캐시 경로 ─────────────────────────────────────────────────────
from config import EXTRACTED_DB


def _cache_path(file_path: str) -> "Path":
    """이미지 캡션/OCR 결과 캐시 경로 (extracted_DB/<name>_<hash>_caption.txt)"""
    import hashlib
    from pathlib import Path
    h = hashlib.md5(file_path.encode()).hexdigest()[:12]
    name = Path(file_path).stem
    return EXTRACTED_DB / f"{name}_{h}_caption.txt"


# ── 캡션 생성 ─────────────────────────────────────────────────────

def _generate_caption(file_path: str) -> str:
    """
    이미지 → 설명 텍스트(캡션) 반환.

    TODO: 원하는 방식으로 구현
    예시 A) BLIP 캡션
      from transformers import BlipProcessor, BlipForConditionalGeneration
      from PIL import Image, ImageOps
      processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
      model     = BlipForConditionalGeneration.from_pretrained(...)
      image     = Image.open(file_path)
      image     = ImageOps.exif_transpose(image)   # iPhone HEIC EXIF 회전 정합
      image     = image.convert("RGB")
      inputs    = processor(image, return_tensors="pt")
      out       = model.generate(**inputs)
      return processor.decode(out[0], skip_special_tokens=True)

    예시 B) OCR (이미지 속 텍스트 추출)
      import pytesseract
      from PIL import Image
      return pytesseract.image_to_string(Image.open(file_path), lang="kor+eng")

    예시 C) CLIP + 텍스트 쿼리 분리 (CLIP 전용 컬렉션 필요)
    """
    raise NotImplementedError("이미지 캡션/OCR 미구현")


# ── 진입점 ────────────────────────────────────────────────────────

def embed(file_path: str) -> dict:
    """
    이미지 파일을 임베딩하여 벡터 저장소에 저장.

    반환:
      {"status": "done",    "chunks": int}
      {"status": "skipped", "reason": str}
      {"status": "error",   "reason": str}
    """
    from embedders.base import make_chunks, encode_texts
    from db.vector_store import upsert_chunks, delete_file

    # 캐시된 캡션이 있으면 재사용
    cache = _cache_path(file_path)
    if cache.exists():
        text = cache.read_text(encoding="utf-8")
    else:
        try:
            # 1. 캡션/OCR → 텍스트
            text = _generate_caption(file_path)
            cache.write_text(text, encoding="utf-8")
        except NotImplementedError as e:
            return {"status": "skipped", "reason": str(e)}
        except Exception as e:
            return {"status": "error", "reason": f"캡션 생성 실패: {e}"}

    if not text.strip():
        return {"status": "skipped", "reason": "텍스트 없음"}

    try:
        # 2. 청킹 (캡션은 짧으므로 보통 1개 청크)
        chunks = make_chunks(text)

        # 3. 임베딩
        vectors = encode_texts(chunks)

        # 4. 저장
        delete_file(file_path)

        file_name = os.path.basename(file_path)
        file_hash = hashlib.md5(file_path.encode()).hexdigest()[:8]

        ids       = [f"{file_hash}_img_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "file_path":   file_path,
                "file_name":   file_name,
                "file_type":   "image",
                "chunk_index": i,
                "chunk_text":  chunk[:300],
            }
            for i, chunk in enumerate(chunks)
        ]

        upsert_chunks(ids=ids, embeddings=vectors, metadatas=metadatas)

        return {"status": "done", "chunks": len(chunks)}

    except Exception as e:
        return {"status": "error", "reason": str(e)}
