"""
공통 임베딩 유틸리티

모델 A (384d) — paraphrase-multilingual-MiniLM-L12-v2
  사용: doc, image
  특징: 50개 언어 지원, 빠름

모델 B (768d) — jhgan/ko-sroberta-multitask
  사용: audio
  특징: 한국어 특화, "겨울"↔"12월" 유사도 등 의미 이해 우수

모델 C (1024d) — intfloat/multilingual-e5-large
  사용: video (M11)
  특징: 한·영 동일 벡터 공간, passage:/query: 접두사 필수

각 모델은 최초 사용 시 HuggingFace Hub에서 자동 다운로드.
"""

from __future__ import annotations

# ── 모델 지연 로딩 ────────────────────────────────────────
_model_mini = None   # 384d
_model_ko   = None   # 768d
_model_e5   = None   # 1024d (video M11)

MODEL_MINI = "paraphrase-multilingual-MiniLM-L12-v2"
MODEL_KO   = "jhgan/ko-sroberta-multitask"
MODEL_E5   = "intfloat/multilingual-e5-large"


def _get_model_mini():
    global _model_mini
    if _model_mini is None:
        from sentence_transformers import SentenceTransformer
        _model_mini = SentenceTransformer(MODEL_MINI)
    return _model_mini


def _get_model_ko():
    global _model_ko
    if _model_ko is None:
        from sentence_transformers import SentenceTransformer
        _model_ko = SentenceTransformer(MODEL_KO)
    return _model_ko


def _get_model_e5():
    global _model_e5
    if _model_e5 is None:
        from sentence_transformers import SentenceTransformer
        _model_e5 = SentenceTransformer(MODEL_E5)
    return _model_e5


# ── 청킹 ──────────────────────────────────────────────
CHUNK_SIZE    = 500   # 글자 수
CHUNK_OVERLAP = 100   # 오버랩 글자 수


def make_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """긴 텍스트를 chunk_size 글자 단위로 분할 (overlap 포함). 빈 청크 제거."""
    text = text.strip()
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + chunk_size].strip())
        start += chunk_size - overlap
    return [c for c in chunks if c]


# ── 384d 임베딩 (doc / image) ─────────────────────────

def encode_texts(texts: list[str]) -> list[list[float]]:
    """텍스트 리스트 → 384d 벡터 리스트."""
    if not texts:
        return []
    return _get_model_mini().encode(texts, convert_to_numpy=True, show_progress_bar=False).tolist()


def encode_query(query: str) -> list[float]:
    """검색 쿼리 → 384d 벡터 (doc/image 컬렉션용)."""
    return encode_texts([query])[0]


# ── 768d 임베딩 (audio) ───────────────────────────────

def encode_texts_ko(texts: list[str]) -> list[list[float]]:
    """텍스트 리스트 → 768d 벡터 리스트 (ko-sroberta)."""
    if not texts:
        return []
    import numpy as np
    vecs = _get_model_ko().encode(
        texts, batch_size=32,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vecs.tolist()


def encode_query_ko(query: str) -> list[float]:
    """검색 쿼리 → 768d 벡터 (audio 컬렉션용)."""
    return encode_texts_ko([query])[0]


# ── 1024d 임베딩 (video M11, e5-large) ───────────────

def encode_query_e5(query: str) -> list[float]:
    """
    검색 쿼리 → 1024d 벡터 (video M11 컬렉션용).
    e5 규칙: 검색 시 "query: " 접두사 필수.
    """
    vec = _get_model_e5().encode(
        f"query: {query}",
        normalize_embeddings=True,
    )
    return vec.tolist()


# ── 쿼리를 모든 모델로 인코딩 ─────────────────────────

def encode_query_all(query: str) -> dict[str, list[float]]:
    """
    검색 쿼리를 모든 모델로 인코딩.
    반환: { "doc": [384d], "image": [384d], "audio": [768d], "video": [1024d] }
    search_all() 에 그대로 전달 가능.
    """
    vec_mini = encode_query(query)
    vec_ko   = encode_query_ko(query)
    vec_e5   = encode_query_e5(query)
    return {
        "doc":   vec_mini,
        "image": vec_mini,
        "audio": vec_ko,
        "video": vec_e5,
    }
