"""scripts/baselines — MIRACL-ko baseline retriever 모음.

각 모듈은 get_retriever() 를 노출하며,
eval_miracl_ko.Retriever Protocol 을 구현한 객체를 반환한다.
"""
from __future__ import annotations

__all__ = ["bm25", "mdpr", "mcontriever", "me5", "bgem3"]
