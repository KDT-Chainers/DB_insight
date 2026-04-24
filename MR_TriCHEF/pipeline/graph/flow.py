"""LangGraph 조립 + 공개 진입점.

사용:
    from pipeline.graph import search_graph
    hits, trace = search_graph(
        query="마이클 조던 농구",
        domain="all",              # "movie" | "music" | "all"
        encoders={"sig": sig_encoder, "bge": bge_encoder},
    )
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.graph import StateGraph, END

from .state import SearchState
from . import nodes as N


@lru_cache(maxsize=1)
def build_graph():
    g = StateGraph(SearchState)

    g.add_node("analyze",       N.analyze_query)
    g.add_node("dense_search",  N.dense_search)
    g.add_node("rewrite_query", N.rewrite_query)
    g.add_node("rerank",        N.rerank)
    g.add_node("return_hits",   N.return_hits)

    g.set_entry_point("analyze")
    g.add_edge("analyze", "dense_search")

    g.add_conditional_edges(
        "dense_search",
        N.route_after_search,
        {
            "return_hits":   "return_hits",
            "rerank":        "rerank",
            "rewrite_query": "rewrite_query",
        },
    )

    g.add_edge("rewrite_query", "dense_search")   # 재검색 루프
    g.add_edge("rerank",        "return_hits")
    g.add_edge("return_hits",   END)

    return g.compile()


def search_graph(query: str, domain: str = "all",
                 encoders: dict[str, Any] | None = None) -> tuple[list, list[str]]:
    app = build_graph()
    init: SearchState = {
        "query_original": query,
        "query_current":  query,
        "domain":         domain,  # type: ignore
        "hits":           [],
        "tries":          0,
        "rerank_done":    False,
        "trace":          [],
        "ctx":            encoders or {},
    }
    # recursion_limit: rewrite→search 사이클 제어. 노드 수 여유 있게.
    final = app.invoke(init, config={"recursion_limit": 25})
    return final.get("hits", []), final.get("trace", [])
