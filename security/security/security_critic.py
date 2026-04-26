"""
security/security_critic.py
──────────────────────────────────────────────────────────────────────────────
Security Critic (Supervisor) — 최종 출력 심사자.

핵심 철학:
    "무엇을 물었는가"가 아니라
    "무엇이 밖으로 나가려 하는가"를 통제한다.

역할:
    GroundingGate 이후, UI 출력 직전에 위치.
    생성된 응답 텍스트를 직접 검사하여 안전 여부를 결정.

    예: 질문 "회의록 요약해줘" → 정상 질문이지만
        응답에 "김철수 계좌번호 123-456-789" 포함 시 → 차단/마스킹

DB 직접 접근 금지 (ABC 원칙):
    입력: user_query, generated_output, feature_map, session_state, policy
    출력: CriticDecision (JSON 직렬화 가능)

디버깅:
    - CriticDecision.to_dict() 로 결과 확인
    - CriticDecision.pii_found_in_output 로 탐지된 PII 확인
    - _scan_output_pii() 를 독립 호출하여 패턴 테스트 가능
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from security.critic_policy import (
    APPROVE,
    APPROVE_MASKED,
    REJECT,
    REGENERATE_WITH_CONSTRAINTS,
    DECISION_TO_ACTION,
    SESSION_WARN_THRESHOLD,
    HIGH_RISK_PII_TYPES,
    REGENERATE_MIN_PII_TYPES,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 심사 결과 타입
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CriticDecision:
    """Security Critic 심사 결과."""
    decision: str                                   # approve | approve_masked | reject | regenerate_with_constraints
    reason: str                                     # 판단 이유 (한국어)
    risk_score: int                                 # 현재 세션 누적 위험도
    action: str                                     # show | mask | block | regenerate
    pii_found_in_output: List[str] = field(default_factory=list)   # 출력에서 탐지된 PII 유형
    constraints: Optional[str] = None              # regenerate 시 제약 조건 설명

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision":            self.decision,
            "reason":              self.reason,
            "risk_score":          self.risk_score,
            "action":              self.action,
            "pii_found_in_output": self.pii_found_in_output,
            "constraints":         self.constraints,
        }

    @property
    def is_approved(self) -> bool:
        return self.decision in (APPROVE, APPROVE_MASKED)

    @property
    def is_blocked(self) -> bool:
        return self.decision == REJECT

    @property
    def needs_regenerate(self) -> bool:
        return self.decision == REGENERATE_WITH_CONSTRAINTS


# ──────────────────────────────────────────────────────────────────────────────
# Security Critic
# ──────────────────────────────────────────────────────────────────────────────

class SecurityCritic:
    """
    최종 출력물 심사자 (Supervisor).

    사용법:
        critic = SecurityCritic()
        decision = critic.review(
            user_query       = "회의록 요약해줘",
            generated_output = "김철수 계좌번호 123-456-789...",
            feature_map      = retrieval_result.feature_map,
            session_state    = session_engine.get_state("session123"),
        )
        if decision.decision == "reject":
            # 차단

    판단 순서:
        1. 세션 자동 차단 여부
        2. Prompt Injection / 우회 시도 탐지
        3. 출력 텍스트 내 PII 직접 스캔
        4. Feature Map 기반 위험 신호
        5. 세션 경고 수준 확인
        6. 최종 결정
    """

    # ── 출력 PII 탐지 패턴 ────────────────────────────────────────────────────
    # 생성된 응답 텍스트를 직접 검사하는 정규식 (저장소 접근 없음).
    # 주의: 한국어 문자는 \w 에 포함되므로 \b 대신 (?<!\d) / (?!\d) 사용.
    _OUTPUT_PII_PATTERNS: List[tuple] = [
        (r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)",                                  "KR_RRN"),
        (r"(?<![A-Z])[A-Z]\d{7,8}(?!\d)",                                   "KR_PASSPORT"),
        (r"(?<!\d)\d{2}-\d{2}-\d{6}-\d{2}(?!\d)",                           "KR_DRIVER_LICENSE"),
        # 전화번호 패턴(010/02/지역번호)은 제외하고 계좌번호만 탐지
        (r"(?<!\d)(?!(?:01[0-9]|02|0[3-9]\d)[-\s])\d{3,4}[-\s]\d{2,4}[-\s]\d{4,6}(?:[-\s]\d{1,3})?(?!\d)", "KR_BANK_ACCOUNT"),
        (r"(?<!\d)\d{3}-\d{2}-\d{5}(?!\d)",                                  "KR_BRN"),
        (r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",              "EMAIL"),
    ]

    # ── Prompt Injection / 우회 탐지 패턴 ────────────────────────────────────
    _BYPASS_PATTERNS: List[str] = [
        r"보안\s*무시",    r"정책\s*무시",   r"규칙\s*무시",
        r"ignore\s+policy", r"ignore\s+security", r"bypass",
        r"jailbreak",      r"이전\s*지시\s*무시",  r"모든\s*규칙\s*무시",
        r"DAN\s*mode",     r"developer\s+mode",
    ]

    # ── 심사 메인 함수 ────────────────────────────────────────────────────────

    def review(
        self,
        user_query: str,
        generated_output: str,
        feature_map: Dict[str, Any],
        session_state: Any,                         # SessionState (session_risk_engine.py)
        policy: Optional[Dict[str, Any]] = None,
        auth_state: Optional[Dict[str, Any]] = None,
    ) -> CriticDecision:
        """
        최종 출력 심사. DB 접근 금지 — 입력값만으로 판단.

        Args:
            user_query:       사용자 원문 질의
            generated_output: 생성된 응답 텍스트 (검색 소스 텍스트 포함)
            feature_map:      Retrieval 결과 feature map
            session_state:    SessionState (누적 위험 상태)
            policy:           추가 정책 오버라이드 (선택)
            auth_state:       인증 상태 (선택, 추후 확장용)

        Returns:
            CriticDecision
        """
        risk_score = int(getattr(session_state, "risk_score", 0))

        # ── 1. 세션 자동 차단 ──────────────────────────────────────────────
        if getattr(session_state, "blocked", False):
            logger.warning("[Critic] 세션 차단 (score=%d)", risk_score)
            return CriticDecision(
                decision=REJECT,
                reason=f"세션 위험도가 임계값을 초과하여 자동 차단되었습니다. (누적={risk_score}점) "
                       "관리자에게 문의하거나 세션을 초기화하세요.",
                risk_score=risk_score,
                action="block",
            )

        # ── 2. Prompt Injection / 우회 시도 탐지 ──────────────────────────
        bypass_target = f"{user_query} {generated_output}"
        if self._detect_bypass(bypass_target):
            logger.warning("[Critic] 우회 시도 탐지")
            return CriticDecision(
                decision=REJECT,
                reason="정책 우회 또는 보안 무력화 시도가 감지되었습니다.",
                risk_score=risk_score,
                action="block",
            )

        # ── 3. 출력 텍스트 내 PII 직접 스캔 ───────────────────────────────
        pii_in_output = self._scan_output_pii(generated_output)

        if pii_in_output:
            types_str = ", ".join(sorted(set(pii_in_output)))
            high_risk_found = set(pii_in_output) & HIGH_RISK_PII_TYPES
            # REGENERATE_MIN_PII_TYPES 개 이상의 고위험 유형이 감지될 때만 재생성.
            # 기본값(1)이면 기존과 동일하게 단일 유형만 탐지돼도 재생성.
            is_high_risk = len(high_risk_found) >= REGENERATE_MIN_PII_TYPES

            if is_high_risk:
                # 고위험 PII (주민번호/여권/계좌) → 조건부 재생성
                logger.warning("[Critic] 출력 내 고위험 PII 탐지: %s", types_str)
                return CriticDecision(
                    decision=REGENERATE_WITH_CONSTRAINTS,
                    reason=f"응답에 고위험 개인정보({types_str})가 포함되어 있습니다. 해당 정보를 제거 후 재생성합니다.",
                    risk_score=risk_score,
                    action="regenerate",
                    pii_found_in_output=list(set(pii_in_output)),
                    constraints=f"다음 개인정보를 절대 포함하지 말 것: {types_str}",
                )
            else:
                # 중위험 PII (전화번호/이메일 등) → 마스킹 허용
                logger.info("[Critic] 출력 내 중위험 PII 탐지 → 마스킹: %s", types_str)
                return CriticDecision(
                    decision=APPROVE_MASKED,
                    reason=f"응답에 개인정보({types_str})가 포함되어 마스킹 처리합니다.",
                    risk_score=risk_score,
                    action="mask",
                    pii_found_in_output=list(set(pii_in_output)),
                )

        # ── 4. Feature Map 기반 위험 신호 ─────────────────────────────────
        bulk_request = feature_map.get("bulk_request", False)
        contains_pii = feature_map.get("contains_pii", False)
        pii_types = [str(t).upper() for t in (feature_map.get("pii_types") or [])]

        if bulk_request:
            logger.warning("[Critic] 대량 추출 신호 → 차단")
            return CriticDecision(
                decision=REJECT,
                reason="대량 개인정보 추출 패턴이 감지되어 차단합니다.",
                risk_score=risk_score,
                action="block",
            )

        # 전화번호(KR_PHONE)만 포함된 경우는 비민감으로 간주 (사용자 정책 반영)
        if contains_pii and pii_types and set(pii_types).issubset({"KR_PHONE", "PHONE_NUMBER"}):
            return CriticDecision(
                decision=APPROVE,
                reason="전화번호는 비민감 정책으로 분류되어 그대로 출력합니다.",
                risk_score=risk_score,
                action="show",
            )

        if contains_pii:
            # 검색 소스에 PII 있었으나 출력엔 직접 노출 안 됨 → 마스킹 표시
            return CriticDecision(
                decision=APPROVE_MASKED,
                reason="검색 소스에 개인정보가 포함되어 마스킹 표시합니다.",
                risk_score=risk_score,
                action="mask",
            )

        # ── 5. 세션 경고 수준 ─────────────────────────────────────────────
        if risk_score >= SESSION_WARN_THRESHOLD:
            logger.info("[Critic] 세션 위험도 경고 수준 (score=%d)", risk_score)
            return CriticDecision(
                decision=APPROVE,
                reason=f"출력물은 안전하나 세션 위험도가 높습니다. (누적={risk_score}점)",
                risk_score=risk_score,
                action="show",
            )

        # ── 6. 최종 승인 ──────────────────────────────────────────────────
        logger.debug("[Critic] 출력 승인 (score=%d)", risk_score)
        return CriticDecision(
            decision=APPROVE,
            reason="출력물에 개인정보가 없습니다.",
            risk_score=risk_score,
            action="show",
        )

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _scan_output_pii(self, text: str) -> List[str]:
        """
        출력 텍스트에서 PII 패턴을 직접 탐지.
        DB 접근 없이 정규식만 사용.
        """
        if not text:
            return []
        found = []
        for pattern, label in self._OUTPUT_PII_PATTERNS:
            if re.search(pattern, text):
                found.append(label)
        return found

    def _detect_bypass(self, text: str) -> bool:
        """Prompt Injection / 우회 키워드 탐지."""
        if not text:
            return False
        for pattern in self._BYPASS_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                logger.warning("[Critic] 우회 패턴 탐지: %r", pattern)
                return True
        return False
