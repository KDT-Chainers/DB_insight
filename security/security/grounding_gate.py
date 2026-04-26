"""
security/grounding_gate.py
──────────────────────────────────────────────────────────────────────────────
Grounding Gate — 검색 결과가 질문과 실질적으로 연결되는지 판단한다.

v2 변경점:
  - meta_index 히트 신호 제거 (단일 인덱스 구조로 불필요)
  - 원문 텍스트가 저장되므로 코사인 유사도가 자연스럽게 높아져 별도 보완 불필요
  - 민감 키워드 임계값 할인만 유지

ABC Rule: 이 모듈은 데이터를 읽거나 저장하지 않는다. 순수 함수 집합.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np

import config

logger = logging.getLogger(__name__)

# 마스킹 손실이 클 수 있는 키워드 → 임계값 할인
_PASSPORT_KW = frozenset({"여권", "passport", "여권번호", "여권사진", "여권 사진", "여권 번호"})
_ID_KW       = frozenset({"주민번호", "주민등록", "rrn", "신분증", "민증"})
_BIZ_KW      = frozenset({"계좌번호", "사업자번호", "사업자등록"})
# 짧은 질의 + 긴 본문 조합에서 유사도가 낮게 나오기 쉬운 유형 → 임계값 완화
_SUMMARYISH_KW = (
    "요약", "줄거리", "핵심", "정리", "간단히", "스토리", "내용", "plot", "summary", "synopsis",
)


def _is_summaryish_query(user_query: str) -> bool:
    q = user_query.strip().lower()
    if not q:
        return False
    for kw in _SUMMARYISH_KW:
        if kw.lower() in q:
            return True
    return False


def _threshold_discount(user_query: str) -> float:
    """민감 키워드가 포함된 질의는 임계값을 낮춘다 (최대 0.10)."""
    q = user_query.lower().replace(" ", "")
    if any(kw.replace(" ", "") in q for kw in _PASSPORT_KW):
        return 0.10
    if any(kw.replace(" ", "") in q for kw in _ID_KW):
        return 0.08
    if any(kw.replace(" ", "") in q for kw in _BIZ_KW):
        return 0.06
    return 0.0


class GroundingGate:
    """
    질문이 검색 결과에 근거가 있는지 판단하는 게이트.

    v2: 원문 텍스트 임베딩이므로 유사도가 자연스럽게 측정됨.
    단순 코사인 유사도 임계값 비교만 수행한다.

    사용법:
        gate = GroundingGate()
        passed = gate.check(user_query="여권 사진 찾아줘", chunks=[...], label="SENSITIVE")
    """

    def check(
        self,
        user_query: str,
        chunks: List[Dict[str, Any]],
        label: str = "NORMAL",
    ) -> bool:
        """
        Grounding 여부를 판단한다.

        Args:
            user_query: 사용자 질의 (원본)
            chunks:     VectorStore 검색 결과
            label:      Qwen 분류 레이블

        Returns:
            True: 근거 있음 → 답변 생성 허용
            False: 근거 없음 → "정보 없음" 반환
        """
        if not chunks:
            logger.info("GroundingGate: chunks 없음 → 차단")
            return False

        # SENSITIVE는 Qwen이 이미 분류·정책 판단을 마쳤으므로 항상 통과
        if str(label).upper() == "SENSITIVE":
            logger.info("GroundingGate: SENSITIVE → 무조건 통과")
            return True

        context = " ".join((c.get("text") or "") for c in chunks[:5]).strip()
        if not context:
            logger.info("GroundingGate: context 텍스트 없음 → 차단")
            return False

        max_ctx = int(getattr(config, "GROUNDING_EMBED_CONTEXT_MAX_CHARS", 3000))
        if len(context) > max_ctx:
            context = context[:max_ctx]
            logger.debug("GroundingGate: context %d자로 절단(유사도 계산용)", max_ctx)

        sim = self._cosine_sim(user_query, context)

        discount = _threshold_discount(user_query)
        if _is_summaryish_query(user_query):
            base_thr = float(getattr(config, "GROUNDING_SIM_THRESHOLD_SUMMARY", 0.07))
        else:
            base_thr = float(config.GROUNDING_SIM_THRESHOLD)
        threshold = max(base_thr - discount, 0.05)

        passed = sim >= threshold
        logger.info(
            "GroundingGate: sim=%.4f thr=%.4f label=%s discount=%.2f → %s",
            sim, threshold, label, discount, "통과" if passed else "차단",
        )
        return passed

    @staticmethod
    def _cosine_sim(text_a: str, text_b: str) -> float:
        """두 텍스트의 임베딩 코사인 유사도를 계산한다."""
        from vectordb.store import embed_texts
        try:
            vecs = embed_texts([text_a, text_b])
            a, b = vecs[0], vecs[1]
            denom = float(np.linalg.norm(a) * np.linalg.norm(b))
            if denom <= 1e-12:
                return 0.0
            return float(np.dot(a, b) / denom)
        except Exception as exc:
            logger.warning("GroundingGate 유사도 계산 실패, 안전 차단: %s", exc)
            return 0.0
