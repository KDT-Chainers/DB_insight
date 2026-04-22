"""embedders/trichef/bgem3_sparse.py — BGE-M3 Sparse 렉시컬 채널 (v2 P2).

BGE-M3 의 `lexical_weights` 출력을 재사용. 토큰 ID → 가중치 dict 형태.
scipy.sparse.csr 매트릭스로 인덱스 저장, 쿼리 시 dot product 로 lexical score.
"""
from __future__ import annotations

import logging

import numpy as np
from scipy import sparse as sp

from embedders.trichef import bgem3_caption_im

logger = logging.getLogger(__name__)

# BGE-M3 은 XLM-RoBERTa 토크나이저 (vocab 250002)
VOCAB_SIZE = 250002


def _encode(texts: list[str], batch_size: int = 32, max_length: int = 1024) -> list[dict]:
    bgem3_caption_im._load()
    out = bgem3_caption_im._model.encode(
        texts,
        batch_size=batch_size,
        max_length=max_length,
        return_dense=False,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    # lexical_weights: list[dict[int, float]] 또는 dict[str,float]
    weights = out["lexical_weights"]
    normalized: list[dict] = []
    for w in weights:
        d = {}
        for k, v in w.items():
            tid = int(k)
            d[tid] = float(v)
        normalized.append(d)
    return normalized


def embed_passage_sparse(texts: list[str], batch_size: int = 32,
                         max_length: int = 1024) -> sp.csr_matrix:
    """패시지 집합 → (N, VOCAB) CSR sparse."""
    if not texts:
        return sp.csr_matrix((0, VOCAB_SIZE), dtype=np.float32)
    rows, cols, data = [], [], []
    weights = _encode(texts, batch_size=batch_size, max_length=max_length)
    for i, d in enumerate(weights):
        for tid, w in d.items():
            if tid < VOCAB_SIZE and w > 0:
                rows.append(i)
                cols.append(tid)
                data.append(w)
    return sp.csr_matrix(
        (data, (rows, cols)),
        shape=(len(texts), VOCAB_SIZE),
        dtype=np.float32,
    )


def embed_query_sparse(text: str, max_length: int = 256) -> sp.csr_matrix:
    """쿼리 → (1, VOCAB) CSR."""
    return embed_passage_sparse([text], batch_size=1, max_length=max_length)


def lexical_scores(q_sparse: sp.csr_matrix, doc_sparse: sp.csr_matrix) -> np.ndarray:
    """q(1,V) · doc(N,V).T → (N,) lexical similarity."""
    if doc_sparse.shape[0] == 0:
        return np.zeros(0, dtype=np.float32)
    scores = (doc_sparse @ q_sparse.T).toarray().ravel()
    return scores.astype(np.float32)
