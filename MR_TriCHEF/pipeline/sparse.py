"""MR_TriCHEF/pipeline/sparse.py — BGE-M3 sparse lexical 채널.

lexical 채널은 현재 beta=0 으로 미사용. import 경로가 깨져도 search() 가
정상 동작해야 하므로 lazy import + ImportError 시 빈 결과 반환으로 방어.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from scipy import sparse as sp

logger = logging.getLogger(__name__)

# ── lazy import: App/backend 경로 의존 없이 시도 ──────────────────────────────
try:
    from scipy import sparse as _sp
    from App.backend.embedders.trichef.bgem3_sparse import (  # type: ignore[import]
        embed_query_sparse as _embed_query_sparse,
        lexical_scores as _lexical_scores,
    )
    try:
        from App.backend.embedders.trichef.bgem3_sparse import (  # type: ignore[import]
            embed_texts_sparse as _embed_texts_sparse,
        )
    except ImportError:
        _embed_texts_sparse = None  # 원본 API 명명에 따라 noop

    _SPARSE_AVAILABLE = True
    logger.debug("[sparse] bgem3_sparse 로드 성공")
except Exception as _e:
    _SPARSE_AVAILABLE = False
    _embed_texts_sparse = None
    logger.debug(f"[sparse] bgem3_sparse 로드 실패 (lexical 채널 비활성): {_e}")


# ── 공개 API — import 실패 시 안전한 빈 결과 반환 ─────────────────────────────

def embed_query_sparse(text: str, max_length: int = 256):
    """쿼리 → (1, VOCAB) CSR. import 실패 시 None 반환."""
    if not _SPARSE_AVAILABLE:
        return None
    return _embed_query_sparse(text, max_length=max_length)  # type: ignore[name-defined]


def embed_texts_sparse(texts: list[str], batch_size: int = 32, max_length: int = 1024):
    """패시지 집합 → CSR sparse. import 실패 시 None 반환."""
    if not _SPARSE_AVAILABLE or _embed_texts_sparse is None:
        return None
    return _embed_texts_sparse(texts, batch_size=batch_size, max_length=max_length)  # type: ignore[misc]


def lexical_scores(q_sparse, doc_sparse) -> np.ndarray:
    """q(1,V) · doc(N,V).T → (N,) lexical similarity. import 실패 시 빈 배열 반환."""
    if not _SPARSE_AVAILABLE or q_sparse is None or doc_sparse is None:
        # doc_sparse 가 없으면 N 을 알 수 없으므로 0-len 반환
        try:
            n = doc_sparse.shape[0] if doc_sparse is not None else 0
        except Exception:
            n = 0
        return np.zeros(n, dtype=np.float32)
    return _lexical_scores(q_sparse, doc_sparse)  # type: ignore[name-defined]
