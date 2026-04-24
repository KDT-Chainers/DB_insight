"""DI_TriCHEF/reranker/post_rerank.py

Non-invasive 재순위화 — 기존 `/api/admin/inspect` 응답을 받아 top-K 행의
텍스트(doc_text/caption)를 가져와 cross-encoder로 재순위화.

App/backend 미변경 원칙(Option B) 준수 — 새 엔드포인트·훅 삽입 없음.

사용 예:
    python DI_TriCHEF/reranker/rerank_cli.py --query "웃고 있는 강아지" --domain image
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 쿼리가 너무 짧으면 cross-encoder 정확도 저하 → 스킵
MIN_QUERY_CHARS = 5
DEFAULT_TOP_K = 20


def should_rerank(query: str) -> bool:
    return len(query.strip()) >= MIN_QUERY_CHARS


def rerank_rows(query: str, rows: list[dict[str, Any]],
                text_provider, top_k: int = DEFAULT_TOP_K,
                fuse_alpha: float = 0.5) -> list[dict[str, Any]]:
    """rows: /api/admin/inspect 의 rows (dense/lexical/asf/fused/id/...).
    text_provider: (row) -> str  (doc_text 또는 캡션 조회 콜백)
    fuse_alpha: 최종 점수 = α·rerank + (1-α)·fused_minmax
    """
    if not rows or not should_rerank(query):
        return rows

    import numpy as np

    top = rows[:top_k]
    texts = [text_provider(r) or "" for r in top]

    from shared.reranker import get_reranker
    scores = get_reranker().score(query, texts)

    # min-max 정규화 (rerank) + fused 정규화 → 가중 결합
    rr = np.asarray(scores, dtype=np.float32)
    rr_norm = (rr - rr.min()) / (rr.max() - rr.min() + 1e-12) if rr.size else rr
    fused = np.asarray([float(r.get("fused", 0.0)) for r in top], dtype=np.float32)
    fu_norm = (fused - fused.min()) / (fused.max() - fused.min() + 1e-12) if fused.size else fused
    combined = fuse_alpha * rr_norm + (1 - fuse_alpha) * fu_norm

    for r, s_raw, s_norm, c in zip(top, rr.tolist(), rr_norm.tolist(), combined.tolist()):
        r["rerank_score"] = float(s_raw)
        r["rerank_norm"] = float(s_norm)
        r["final_score"] = float(c)

    top_sorted = sorted(top, key=lambda x: x.get("final_score", 0.0), reverse=True)
    # top_k 이후 rows 는 원순서 유지(재순위화 대상 외)
    for i, r in enumerate(top_sorted, 1):
        r["reranked_rank"] = i
    return top_sorted + rows[top_k:]
