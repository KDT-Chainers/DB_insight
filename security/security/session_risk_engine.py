"""
security/session_risk_engine.py
──────────────────────────────────────────────────────────────────────────────
세션 단위 위험도 누적 관리 엔진 (규칙 기반, ML 없음).

문제:
  "신한은행 계좌 보여줘"
  "우리은행 계좌 보여줘"
  "카카오뱅크 계좌 보여줘"
  → 각각은 SENSITIVE지만 분할 공격으로 합산하면 대규모 유출 가능.

해결:
  세션 전체에서 이벤트를 누적하고 임계값 초과 시 자동 차단.

디버깅:
  - SessionState.to_dict() 로 현재 상태 확인 가능
  - logger.debug 로 이벤트별 점수 변화 추적 가능
  - reset_session() 으로 테스트 시 초기화 가능

ABC: 상태 관리만. DB·외부통신 없음.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from security.critic_policy import (
    RISK_EVENTS,
    SESSION_BLOCK_THRESHOLD,
    SESSION_WARN_THRESHOLD,
    RAPID_REPEAT_WINDOW_SEC,
    RAPID_REPEAT_COUNT,
    INSTITUTION_KEYWORDS,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 세션 상태 데이터 구조
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionState:
    """세션 한 건의 누적 위험 상태."""
    session_id: str
    risk_score: int = 0
    blocked: bool = False
    warned: bool = False                                        # 경고 수준 도달 여부
    request_history: List[Dict[str, Any]] = field(default_factory=list)
    pii_type_counts: Dict[str, int] = field(default_factory=dict)    # PII 유형별 요청 횟수
    institution_set: set = field(default_factory=set)                 # 조회된 금융기관 집합
    event_log: List[Dict[str, Any]] = field(default_factory=list)     # 감사용 이벤트 로그

    def to_dict(self) -> Dict[str, Any]:
        """감사 로그 / UI 표시용 직렬화."""
        return {
            "session_id":        self.session_id,
            "risk_score":        self.risk_score,
            "blocked":           self.blocked,
            "warned":            self.warned,
            "request_count":     len(self.request_history),
            "pii_type_counts":   dict(self.pii_type_counts),
            "institution_count": len(self.institution_set),
            "institutions":      list(self.institution_set),
        }


# ──────────────────────────────────────────────────────────────────────────────
# 세션 위험 엔진
# ──────────────────────────────────────────────────────────────────────────────

class SessionRiskEngine:
    """
    세션 단위 위험도 누적 관리.

    사용법:
        engine = SessionRiskEngine()
        state = engine.record_event("session123", "sensitive_request",
                                    pii_types=["KR_BANK_ACCOUNT"],
                                    user_query="신한 계좌 알려줘")
        if state.blocked:
            # 차단 처리
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}

    # ── 공개 API ───────────────────────────────────────────────────────────────

    def get_or_create(self, session_id: str) -> SessionState:
        """세션 상태를 가져오거나 새로 생성한다."""
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id)
            logger.debug("[SessionRisk] 새 세션 생성: %s", session_id)
        return self._sessions[session_id]

    def get_state(self, session_id: str) -> SessionState:
        """현재 세션 상태를 반환한다 (없으면 생성)."""
        return self.get_or_create(session_id)

    def record_event(
        self,
        session_id: str,
        event_type: str,
        pii_types: Optional[List[str]] = None,
        user_query: str = "",
    ) -> SessionState:
        """
        이벤트를 기록하고 위험 점수를 누적한다.

        Args:
            session_id:  세션 식별자
            event_type:  RISK_EVENTS 키 (critic_policy.py 참고)
            pii_types:   이번 요청에서 탐지된 PII 유형 목록
            user_query:  원본 질의 (반복·기관 탐지용)

        Returns:
            업데이트된 SessionState
        """
        state = self.get_or_create(session_id)

        # 이미 차단된 세션은 점수 누적 중단 (차단 상태 유지)
        if state.blocked:
            logger.debug("[SessionRisk] 이미 차단된 세션: %s", session_id)
            return state

        now = time.time()
        added_score = RISK_EVENTS.get(event_type, 0)
        reasons: List[str] = [event_type]

        # ── 빠른 반복 요청 탐지 ───────────────────────────────────────────────
        recent = [r for r in state.request_history
                  if now - r["ts"] <= RAPID_REPEAT_WINDOW_SEC]
        if len(recent) >= RAPID_REPEAT_COUNT:
            extra = RISK_EVENTS.get("rapid_repeat_request", 3)
            added_score += extra
            reasons.append(f"rapid_repeat+{extra}")
            logger.warning("[SessionRisk] 빠른 반복 요청 (session=%s, +%d)", session_id, extra)

        # ── 동일 PII 유형 반복 탐지 ──────────────────────────────────────────
        if pii_types:
            for pt in pii_types:
                prev_count = state.pii_type_counts.get(pt, 0)
                if prev_count >= 1:
                    extra = RISK_EVENTS.get("repeated_same_pii_type", 2)
                    added_score += extra
                    reasons.append(f"repeated_{pt}+{extra}")
                    logger.warning(
                        "[SessionRisk] 동일 PII 유형 반복 (session=%s, type=%s, +%d)",
                        session_id, pt, extra,
                    )
                state.pii_type_counts[pt] = prev_count + 1

        # ── 다수 금융기관 순차 조회 탐지 ─────────────────────────────────────
        if user_query:
            detected_institutions = [
                kw for kw in INSTITUTION_KEYWORDS if kw in user_query
            ]
            for inst in detected_institutions:
                state.institution_set.add(inst)

            if len(state.institution_set) >= 2:
                extra = RISK_EVENTS.get("multi_institution_query", 4)
                added_score += extra
                reasons.append(f"multi_institution+{extra}")
                logger.warning(
                    "[SessionRisk] 다수 기관 순차 조회 (session=%s, institutions=%s, +%d)",
                    session_id, list(state.institution_set), extra,
                )

        # ── 점수 누적 ─────────────────────────────────────────────────────────
        state.risk_score += added_score
        state.request_history.append({"ts": now, "query": user_query, "event": event_type})
        state.event_log.append({
            "ts":       time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "event":    event_type,
            "added":    added_score,
            "total":    state.risk_score,
            "reasons":  reasons,
        })

        # ── 임계값 판정 ───────────────────────────────────────────────────────
        if state.risk_score >= SESSION_BLOCK_THRESHOLD and not state.blocked:
            state.blocked = True
            logger.warning(
                "[SessionRisk] 세션 자동 차단 (session=%s, score=%d >= %d)",
                session_id, state.risk_score, SESSION_BLOCK_THRESHOLD,
            )
        elif state.risk_score >= SESSION_WARN_THRESHOLD and not state.warned:
            state.warned = True
            logger.info(
                "[SessionRisk] 세션 경고 수준 도달 (session=%s, score=%d >= %d)",
                session_id, state.risk_score, SESSION_WARN_THRESHOLD,
            )

        logger.debug(
            "[SessionRisk] event=%s added=%d total=%d (session=%s)",
            event_type, added_score, state.risk_score, session_id,
        )
        return state

    def reset_session(self, session_id: str) -> None:
        """세션 초기화 (테스트·관리자용)."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info("[SessionRisk] 세션 초기화: %s", session_id)

    def all_sessions_summary(self) -> List[Dict[str, Any]]:
        """전체 세션 상태 요약 반환 (감사 로그·UI용)."""
        return [s.to_dict() for s in self._sessions.values()]
