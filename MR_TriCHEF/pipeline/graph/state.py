"""그래프 상태 스키마."""
from __future__ import annotations

from typing import Any, Literal, TypedDict


class SearchState(TypedDict, total=False):
    query_original: str
    query_current:  str
    domain:         Literal["movie", "music", "all"]

    # 쿼리 분석
    query_type:     Literal["visual", "textual", "mixed"]
    weights:        tuple[float, float, float]      # α·dense + β·lexical + γ·asf

    # 검색 결과
    hits:           list                             # list[SearchHit]
    top1_z:         float
    top1_gap:       float                            # top1 z - top3 z 평균

    # 루프 제어
    tries:          int
    rerank_done:    bool

    # 디버깅/추적
    trace:          list[str]

    # 런타임 컨텍스트 (encoder handles 등) — graph 외부에서 주입
    ctx:            dict[str, Any]
