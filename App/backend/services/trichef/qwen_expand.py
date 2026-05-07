"""services/trichef/qwen_expand.py — 쿼리 paraphrase + 벡터 평균."""
from __future__ import annotations

import logging

import numpy as np

from config import TRICHEF_CFG
from embedders.trichef import qwen_caption

logger = logging.getLogger(__name__)


def expand(query: str) -> list[str]:
    if not TRICHEF_CFG["EXPAND_QUERY_ENABLED"]:
        return [query]
    try:
        variants = qwen_caption.paraphrase(query, n=TRICHEF_CFG["EXPAND_QUERY_N"])
    except Exception as e:
        logger.warning(f"[expand] Qwen 실패 ({e}) — 원본만")
        return [query]
    q_norm = query.strip()
    seen = {q_norm}
    dedup: list[str] = []
    for v in variants:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            dedup.append(v)
    return [query] + dedup[: TRICHEF_CFG["EXPAND_QUERY_N"]]


def avg_normalize(vecs: np.ndarray) -> np.ndarray:
    if vecs.ndim == 1:
        v = vecs.astype(np.float32)
    else:
        v = vecs.astype(np.float32).mean(axis=0)
    n = float(np.linalg.norm(v))
    return v / (n + 1e-12)
