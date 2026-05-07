"""Attention-Similarity-Filter — 쿼리↔세그먼트 어휘 오버랩 기반 보정 점수.

App/backend/services/trichef/asf_filter.py 포팅. 한글 bigram 역색인으로
조사·복합어 매칭을 확장.

검색 수식: final = α·dense + β·lexical + γ·asf
"""
from __future__ import annotations

import math
import numpy as np

from .vocab import tokenize


_bigram_index_cache: dict[int, dict[str, list[str]]] = {}


def _get_kr_bigram_index(vocab: dict) -> dict[str, list[str]]:
    key = id(vocab)
    idx = _bigram_index_cache.get(key)
    if idx is not None:
        return idx
    idx = {}
    for vt in vocab:
        if not any("\uac00" <= c <= "\ud7a3" for c in vt):
            continue
        seen = set()
        for i in range(len(vt) - 1):
            bg = vt[i:i+2]
            if bg in seen:
                continue
            seen.add(bg)
            idx.setdefault(bg, []).append(vt)
    _bigram_index_cache[key] = idx
    return idx


def asf_scores(query: str, doc_token_sets: list[dict[str, float]],
               vocab: dict) -> np.ndarray:
    """score_i = Σ_{t ∈ Q ∩ D_i} idf(t) / ||Q||_idf  → min-max [0,1].

    한글 쿼리는 vocab 내 **상위 토큰의 substring 포함** 조건으로도 매칭.
    """
    n = len(doc_token_sets)
    if n == 0:
        return np.zeros(0, dtype=np.float32)

    raw = tokenize(query)
    if not raw:
        return np.zeros(n, dtype=np.float32)

    q_set: set[str] = set()
    kr_idx = None
    for t in raw:
        if t in vocab:
            q_set.add(t)
        if any("\uac00" <= c <= "\ud7a3" for c in t) and len(t) >= 2:
            if kr_idx is None:
                kr_idx = _get_kr_bigram_index(vocab)
            candidates: set[str] = set()
            for i in range(len(t) - 1):
                bucket = kr_idx.get(t[i:i+2])
                if bucket:
                    candidates.update(bucket)
            for vt in candidates:
                if t in vt:
                    q_set.add(vt)
    if not q_set:
        return np.zeros(n, dtype=np.float32)
    q_norm = math.sqrt(sum(vocab[t]["idf"] ** 2 for t in q_set)) or 1.0

    scores = np.zeros(n, dtype=np.float32)
    for i, d in enumerate(doc_token_sets):
        if not d:
            continue
        inter = q_set & d.keys()
        if not inter:
            continue
        num = sum(d[t] for t in inter)
        scores[i] = num / q_norm

    mx = float(scores.max())
    if mx > 0:
        scores = scores / mx
    return scores
