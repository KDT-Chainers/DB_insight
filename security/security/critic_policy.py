"""
security/critic_policy.py
──────────────────────────────────────────────────────────────────────────────
Security Critic 정책 상수 및 임계값 정의.

이 파일만 수정하면 위험도 점수 / 임계값 전체 변경 가능.
로직 코드 수정 불필요.

ABC: 상수 정의만. 상태·DB·외부통신 없음.
"""
from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────────────
# Critic 결정 상수
# ──────────────────────────────────────────────────────────────────────────────

APPROVE                     = "approve"                    # 그대로 출력 허용
APPROVE_MASKED              = "approve_masked"             # 마스킹 후 출력
REJECT                      = "reject"                     # 완전 차단
REGENERATE_WITH_CONSTRAINTS = "regenerate_with_constraints"  # 조건부 재생성

# 결정 → UI action 매핑
DECISION_TO_ACTION = {
    APPROVE:                     "show",
    APPROVE_MASKED:              "mask",
    REJECT:                      "block",
    REGENERATE_WITH_CONSTRAINTS: "regenerate",
}

# ──────────────────────────────────────────────────────────────────────────────
# 세션 위험 이벤트 점수표
# ──────────────────────────────────────────────────────────────────────────────
# 튜닝 포인트: 점수만 바꾸면 민감도 조절 가능

RISK_EVENTS: dict = {
    "sensitive_request":        2,   # SENSITIVE 질의
    "full_view_click":          3,   # 전체 보기 클릭
    "repeated_same_pii_type":   2,   # 동일 PII 유형 반복 요청
    "multi_institution_query":  4,   # 다수 금융기관 순차 조회
    "rapid_repeat_request":     3,   # 짧은 시간 내 반복 요청
    "policy_bypass_attempt":    5,   # 정책 우회 시도 (Prompt Injection)
    "dangerous_request":        6,   # DANGEROUS 질의
    "pii_in_output_detected":   4,   # 출력에서 PII 직접 탐지
    "regenerate_triggered":     2,   # regenerate 발생
    "bulk_request":             5,   # 대량 추출 시도
}

# ──────────────────────────────────────────────────────────────────────────────
# 세션 임계값
# ──────────────────────────────────────────────────────────────────────────────

SESSION_WARN_THRESHOLD  = 8    # 경고 수준 (출력은 허용, 경고 표시)
SESSION_BLOCK_THRESHOLD = 15   # 자동 차단 수준

# ──────────────────────────────────────────────────────────────────────────────
# 빠른 반복 요청 탐지 파라미터
# ──────────────────────────────────────────────────────────────────────────────

RAPID_REPEAT_WINDOW_SEC = 30   # 탐지 시간 창 (초)
RAPID_REPEAT_COUNT      = 3    # 창 내 허용 요청 수 초과 시 탐지

# ──────────────────────────────────────────────────────────────────────────────
# 고위험 PII 유형 (출력 탐지 시 regenerate 트리거)
# ──────────────────────────────────────────────────────────────────────────────

HIGH_RISK_PII_TYPES = frozenset({
    "KR_RRN",            # 주민등록번호
    "KR_PASSPORT",       # 여권번호
    "KR_BANK_ACCOUNT",   # 계좌번호
    "KR_DRIVER_LICENSE", # 운전면허번호
})

# regenerate_with_constraints 를 실제로 발동할 최소 고위험 PII 탐지 건수.
# 1 = 1개 유형만 감지돼도 재생성 (기존 동작, 보안 우선).
# 2 이상으로 높이면 복합 노출일 때만 재생성 → LLM 재호출 횟수 감소.
# SUMMARY_USE_LLM=False 환경에서는 orchestrator 가 재호출 자체를 건너뛰므로
# 이 값을 바꾸지 않아도 속도에 영향 없음.
REGENERATE_MIN_PII_TYPES: int = 1

# 금융기관 키워드 (다수 기관 순차 조회 탐지용)
INSTITUTION_KEYWORDS = [
    "신한", "kb", "국민", "하나", "우리", "농협", "기업", "산업",
    "카카오뱅크", "토스뱅크", "케이뱅크", "씨티", "sc제일",
]
