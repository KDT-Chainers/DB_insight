"""
agents/retrieval_agent.py
──────────────────────────────────────────────────────────────────────────────
검색 에이전트 — 단일 인덱스 원문 검색.

ABC 권한: [B] 민감 데이터(VectorDB) 접근
금지:     [A] 신뢰불가 입력 직접 처리  /  [C] 외부 통신·상태 변경

v2 변경점:
  - meta_index / secure_index 검색 제거
  - 단일 VectorStore.search() 호출
  - 검색 결과에 has_pii, pii_types, display_masked 포함 → Feature Map에 반영
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

import config
from harness.safe_tools import CAP_B, enforce_abc, safe_vector_search
from vectordb.store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """검색 결과"""
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    feature_map: Dict[str, Any] = field(default_factory=dict)


class RetrievalAgent:
    """
    단일 VectorStore 검색 전담 에이전트.

    ABC 원칙:
      capabilities = {CAP_B}  →  B 만 보유
      신뢰불가 입력 직접 처리 금지 (Orchestrator가 정제해서 넘겨줌)
      외부 API 호출 금지
    """

    CAPABILITIES = {CAP_B}

    def __init__(self, store: VectorStore) -> None:
        enforce_abc("RetrievalAgent", self.CAPABILITIES)
        self._store = store

    # ── 공개 API ───────────────────────────────────────────────────────────────

    def retrieve(
        self,
        sanitized_query: str,
        top_k: int = config.TOP_K,
    ) -> RetrievalResult:
        """
        정제된 쿼리로 VectorStore를 검색하고 Feature Map을 생성한다.

        v2: 원문 임베딩 인덱스 단일 검색.
        PII 유형은 청크 메타데이터에서 읽어 Feature Map에 반영한다.

        Args:
            sanitized_query: Orchestrator가 전처리한 쿼리
            top_k:           반환할 청크 수 (최대 50)

        Returns:
            RetrievalResult (청크 목록 + Feature Map)
        """
        chunks      = safe_vector_search(self._store, sanitized_query, top_k)
        feature_map = self._store.build_feature_map(chunks, sanitized_query)

        logger.info(
            "RetrievalAgent: %d청크 반환 / PII포함=%s / types=%s",
            len(chunks),
            feature_map.get("contains_pii"),
            feature_map.get("pii_types"),
        )
        return RetrievalResult(chunks=chunks, feature_map=feature_map)
