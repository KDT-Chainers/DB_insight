"""LangGraph 노드 정의.

각 노드는 partial state 를 받아 업데이트할 필드 dict 반환. LangGraph 가 merge.

디자인 원칙:
- 모든 노드는 순수함수 (side effect 없음)
- 외부 리소스(encoders) 는 state["ctx"] 로 주입
- 실패 시 trace 에 로그만 남기고 빈 결과 반환 (전파 금지)
"""
from __future__ import annotations

import re
from typing import Any

from . import rewrite as rw
from .state import SearchState


_VISUAL_HINTS = re.compile(
    r"장면|프레임|색|배경|영상|사진|화면|빨간|파란|녹색|덩크|슛|표정|"
    r"scene|color|image|frame|visual|red|blue|green|dunk"
)
_TEXTUAL_HINTS = re.compile(
    r"설명|말했|발음|대사|가사|뉴스|전체|요약|제목|"
    r"said|lyrics|caption|description|news|summary"
)

# z-score 임계값
TAU_HIGH   = 3.0      # 확신 → 바로 반환
TAU_LOW    = 1.0      # 재작성 트리거
MAX_TRIES  = 2


# ─── 1. 쿼리 분석 ────────────────────────────────────────────────────────────
def analyze_query(state: SearchState) -> dict:
    q = state.get("query_current") or state.get("query_original", "")
    vis  = bool(_VISUAL_HINTS.search(q))
    txt  = bool(_TEXTUAL_HINTS.search(q))
    if vis and not txt:
        qtype, weights = "visual", (0.85, 0.0, 0.15)
    elif txt and not vis:
        qtype, weights = "textual", (0.65, 0.0, 0.35)
    else:
        qtype, weights = "mixed", (0.75, 0.0, 0.25)
    trace = state.get("trace", []) + [f"analyze: type={qtype} weights={weights}"]
    return {"query_type": qtype, "weights": weights, "trace": trace}


# ─── 2. Dense + ASF 검색 ────────────────────────────────────────────────────
def dense_search(state: SearchState) -> dict:
    from .. import search as S

    ctx    = state.get("ctx", {})
    domain = state.get("domain", "all")
    q      = state.get("query_current") or state.get("query_original", "")
    weights = state.get("weights")
    trace  = state.get("trace", [])

    prev_w = getattr(S, "WEIGHTS", None)
    if weights and prev_w is not None:
        # 가중치를 임시로 override (동일 프로세스 내 단일 사용자 전제)
        S.WEIGHTS = {"movie": weights, "music": weights}

    try:
        hits: list = []
        if domain in ("movie", "all"):
            hits += S.search_movie(q, topk=10,
                                   siglip_encoder=ctx.get("sig"),
                                   bge_encoder=ctx.get("bge"))
        if domain in ("music", "all"):
            hits += S.search_music(q, topk=10,
                                   bge_encoder=ctx.get("bge"))
    finally:
        if prev_w is not None:
            S.WEIGHTS = prev_w

    hits.sort(key=lambda h: -h.score)
    top1_z = float(hits[0].score) if hits else -10.0
    # top3 평균과의 차이 — 랭킹 모호도
    top3_mean = float(sum(h.score for h in hits[:3]) / max(len(hits[:3]), 1)) if hits else -10.0
    gap = top1_z - top3_mean

    trace = trace + [f"search: domain={domain} q='{q[:40]}' top1_z={top1_z:.2f} gap={gap:.2f}"]
    return {"hits": hits, "top1_z": top1_z, "top1_gap": gap, "trace": trace}


# ─── 3. Confidence gate ─────────────────────────────────────────────────────
def route_after_search(state: SearchState) -> str:
    z      = state.get("top1_z", 0.0)
    tries  = state.get("tries", 0)
    reran  = state.get("rerank_done", False)

    if z >= TAU_HIGH:
        return "return_hits"
    if z >= TAU_LOW:
        # 모호 구간: rerank 한 번만
        return "return_hits" if reran else "rerank"
    # z < LOW
    if tries >= MAX_TRIES:
        return "return_hits" if reran else "rerank"
    return "rewrite_query"


# ─── 4. 쿼리 재작성 ──────────────────────────────────────────────────────────
def rewrite_query(state: SearchState) -> dict:
    q_prev  = state.get("query_current") or state.get("query_original", "")
    q_new   = rw.rewrite(q_prev)
    tries   = state.get("tries", 0) + 1
    trace   = state.get("trace", []) + [f"rewrite[{tries}]: '{q_prev}' → '{q_new}'"]
    return {"query_current": q_new, "tries": tries, "trace": trace}


# ─── 5. Rerank (Phase 2 BGE-reranker 통합 예정) ─────────────────────────────
def rerank(state: SearchState) -> dict:
    """현 단계는 placeholder — Phase 2 에서 BGE-reranker-v2-m3 연결."""
    trace = state.get("trace", []) + ["rerank: skipped (Phase 2 미구현)"]
    return {"rerank_done": True, "trace": trace}


# ─── 6. 최종 반환 포인트 ────────────────────────────────────────────────────
def return_hits(state: SearchState) -> dict:
    # top-K 정리, 나머지 잘라냄
    hits = state.get("hits", [])[:5]
    trace = state.get("trace", []) + [f"return: {len(hits)} hits"]
    return {"hits": hits, "trace": trace}
