"""
security/summary_guard.py
──────────────────────────────────────────────────────────────────────────────
Summary 전용 보안 가드.

필수 3단 보호:
  1) Prompt Constraint      : SummaryAgent 내부 규칙
  2) Output Re-scan         : 생성된 summary 텍스트 재검사(보호 PII만)
  3) Critic Mandatory Gate  : SecurityCritic 승인 후에만 최종 출력
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Dict, List, Optional

from agents.summary import SummaryAgent, SummaryResult
from security.critic_policy import APPROVE_MASKED
from security.pii_detector import PIIDetector
from security.regenerate_handler import strip_pii_from_output
from security.security_critic import SecurityCritic
from security.session_risk_engine import SessionRiskEngine

logger = logging.getLogger(__name__)


class SummaryGuard:
    """요약 결과를 최종 출력 전에 안전하게 게이팅한다."""

    # Output re-scan 대상(요구사항): 보호 PII 5종만 검사
    _SUMMARY_PROTECTED = frozenset({
        "KR_RRN",
        "KR_PASSPORT",
        "KR_DRIVER_LICENSE",
        "KR_BANK_ACCOUNT",
        "KR_BRN",
    })

    def __init__(
        self,
        summary_agent: SummaryAgent,
        *,
        pii_detector: Optional[PIIDetector] = None,
        critic: Optional[SecurityCritic] = None,
        session_engine: Optional[SessionRiskEngine] = None,
        max_regenerate: int = 2,
    ) -> None:
        self._summary_agent = summary_agent
        self._pii_detector = pii_detector or PIIDetector(qwen_classifier=None)
        self._critic = critic or SecurityCritic()
        self._session_engine = session_engine or SessionRiskEngine()
        self._session_id = "summary-default-session"
        self._max_regenerate = max(1, int(max_regenerate))

    def summarize_secure(
        self,
        user_query: str,
        chunks: List[Dict[str, Any]],
        feature_map: Dict[str, Any],
    ) -> SummaryResult:
        """
        요약 생성 + 재검사 + Critic 승인까지 강제한다.
        """
        base = self._summary_agent.summarize(user_query, chunks)
        if not base.is_ok():
            return base

        attempt = 0
        current = base
        while attempt <= self._max_regenerate:
            text = (current.text or "").strip()
            if not text:
                return SummaryResult(
                    text="요약 결과가 비어 있습니다.",
                    error="empty_summary_output",
                    source_chunk_count=current.source_chunk_count,
                )

            # 2차 방어: Summary output 자체 PII 재검사 (보호 5종만)
            rescan_types = self._rescan_summary_output(text)
            if rescan_types:
                self._session_engine.record_event(
                    self._session_id,
                    "pii_in_output_detected",
                    pii_types=rescan_types,
                    user_query=user_query,
                )
                if attempt >= self._max_regenerate:
                    safe_text = strip_pii_from_output(text, pii_types=rescan_types)
                    return replace(current, text=safe_text, regenerated=True)
                attempt += 1
                constraints = (
                    "주민번호/계좌번호/여권번호/운전면허번호/사업자등록번호를 절대 포함하지 말고 "
                    "3~5줄로 다시 요약하라."
                )
                current = self._summary_agent.summarize_with_constraints(
                    user_query, chunks, constraints=constraints,
                )
                continue

            # 3차 방어: Critic mandatory
            state = self._session_engine.get_state(self._session_id)
            decision = self._critic.review(
                user_query=user_query,
                generated_output=text,
                feature_map=feature_map,
                session_state=state,
            )
            logger.info("[SummaryGuard] critic=%s action=%s", decision.decision, decision.action)

            if decision.needs_regenerate:
                self._session_engine.record_event(
                    self._session_id,
                    "regenerate_triggered",
                    pii_types=decision.pii_found_in_output,
                    user_query=user_query,
                )
                if attempt >= self._max_regenerate:
                    safe_text = strip_pii_from_output(text, pii_types=decision.pii_found_in_output)
                    return replace(current, text=safe_text, regenerated=True)
                attempt += 1
                current = self._summary_agent.summarize_with_constraints(
                    user_query,
                    chunks,
                    constraints=decision.constraints or "민감정보를 제거하고 3~5줄로 다시 요약하라.",
                )
                continue

            if decision.is_blocked:
                return SummaryResult(
                    text="",
                    error=f"summary_blocked_by_critic: {decision.reason}",
                    source_chunk_count=current.source_chunk_count,
                )

            if decision.decision == APPROVE_MASKED:
                masked = strip_pii_from_output(text, pii_types=decision.pii_found_in_output)
                return replace(current, text=masked)

            return current

        return SummaryResult(
            text="",
            error="summary_guard_exhausted",
            source_chunk_count=current.source_chunk_count,
        )

    def _rescan_summary_output(self, text: str) -> List[str]:
        """
        Summary output만 재검사한다.
        요구사항에 맞춰 보호 PII 5종만 반환한다.
        """
        results = self._pii_detector.scan_chunks([text], language="ko")
        if not results:
            return []
        found: List[str] = []
        for f in results[0].findings:
            et = str(f.entity_type).upper()
            if et in self._SUMMARY_PROTECTED and et not in found:
                found.append(et)
        return found

