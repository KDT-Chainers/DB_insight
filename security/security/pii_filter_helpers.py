"""
pii_filter_helpers.py
──────────────────────────────────────────────────────────────────────────────
PII 탐지 후처리·정책용 상수.

목적:
  1) 전화번호·이메일은 이 프로젝트에서 「민감 PII」로 취급하지 않는다.
     → 업로드 모달, 마스킹, PRS 노출, 임베딩 키워드 보강에서 제외.
  2) 계좌번호(KR_BANK_ACCOUNT) 오탐을 줄이기 위해
     은행명 또는 계좌 관련 키워드가 주변 문맥에 있을 때만 인정한다.
  3) 동일 문자열이 청크 안에서 과도하게 반복되면(표·푸터 등) 무시한다.

Presidio / 커스텀 Recognizer는 그대로 두고, scan_chunks 단계에서 위 규칙을 강제한다.
"""
from __future__ import annotations

import logging
import re
from typing import FrozenSet, List, Set, Tuple

import config

logger = logging.getLogger(__name__)

# ── 정책: 민감 PII로 취급하는 유형만 (브레이크 모달·마스킹·PRS·임베딩 보강) ──
POLICY_PROTECTED_PII_TYPES: FrozenSet[str] = frozenset({
    "KR_RRN",
    "KR_PASSPORT",
    "KR_DRIVER_LICENSE",
    "KR_BANK_ACCOUNT",
    "KR_BRN",
})

# 정책에서 완전히 제외 (탐지되어도 PII로 간주하지 않음)
POLICY_IGNORED_PII_TYPES: FrozenSet[str] = frozenset({
    "KR_PHONE",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "CREDIT_CARD",
    "IBAN_CODE",
})

# 은행명 (일부 약칭 포함) — 주변 문맥에 하나라도 있어야 계좌 후보 인정
BANK_NAMES_FOR_CONTEXT: Tuple[str, ...] = (
    "국민은행", "KB국민", "KB", "신한은행", "신한", "우리은행", "우리",
    "하나은행", "하나", "카카오뱅크", "카카오", "농협", "NH", "NH농협",
    "기업은행", "IBK", "SC제일은행", "제일은행", "SC은행", "우체국",
    "토스뱅크", "토스", "한국은행", "산업은행", "수협", "씨티은행",
)

# 계좌 관련 키워드 — 은행명이 없어도 이 키워드 + 숫자 패턴이면 인정
ACCOUNT_KEYWORDS_FOR_CONTEXT: Tuple[str, ...] = (
    "계좌", "계좌번호", "입금", "송금", "통장", "예금주", "입금처",
    "계좌이체", "이체", "출금", "account", "bank",
)

# 동일 매칭 문자열이 청크에서 이 횟수를 넘으면 표·푸터 반복으로 간주하고 제외
_REPEAT_IGNORE_THRESHOLD = 5

# 문맥 윈도우 (글자 수, 앞뒤)
_CONTEXT_WINDOW_CHARS = 120


def is_policy_protected(entity_type: str) -> bool:
    return str(entity_type).upper() in POLICY_PROTECTED_PII_TYPES


def filter_to_protected_pii_types(types: List[str]) -> List[str]:
    """리스트에서 정책 보호 대상만 남긴다 (순서 유지, 중복 제거)."""
    out: List[str] = []
    seen: Set[str] = set()
    for t in types:
        u = str(t).upper()
        if u in POLICY_PROTECTED_PII_TYPES and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def count_nonoverlapping(haystack: str, needle: str) -> int:
    """겹치지 않게 needle 이 몇 번 나오는지 센다."""
    if not needle:
        return 0
    n, pos, c = len(needle), 0, 0
    while True:
        i = haystack.find(needle, pos)
        if i < 0:
            break
        c += 1
        pos = i + n
    return c


def bank_account_has_required_context(chunk_text: str, start: int, end: int) -> bool:
    """
    계좌번호로 인정하려면 반드시 다음 중 하나:
      - 은행명이 윈도우 안에 있음
      - 계좌 관련 키워드가 윈도우 안에 있음

    숫자열만 있는 경우(보고서 번호·표 등)는 False.
    """
    lo = max(0, start - _CONTEXT_WINDOW_CHARS)
    hi = min(len(chunk_text), end + _CONTEXT_WINDOW_CHARS)
    window = chunk_text[lo:hi]

    w_lower = window.lower()
    for name in BANK_NAMES_FOR_CONTEXT:
        if name.lower() in w_lower:
            return True
    for kw in ACCOUNT_KEYWORDS_FOR_CONTEXT:
        if kw.lower() in w_lower:
            return True
    return False


def should_drop_repeated_match(chunk_text: str, matched_text: str) -> bool:
    """동일 매칭 문자열이 임계값 초과 반복이면 True (탐지 제외)."""
    if not matched_text or len(matched_text.strip()) < 4:
        return False
    cnt = count_nonoverlapping(chunk_text, matched_text.strip())
    return cnt > _REPEAT_IGNORE_THRESHOLD


def log_pii_debug(
    action: str,
    entity_type: str,
    matched_text: str,
    chunk_text: str,
    start: int,
    end: int,
    reason: str = "",
) -> None:
    """
    PIIDEBUG=1 일 때만 상세 로그.
    오탐 원인(문맥·반복) 분석용.
    """
    if not getattr(config, "PIIDEBUG", False):
        return
    before = chunk_text[max(0, start - 40) : start]
    after = chunk_text[end : min(len(chunk_text), end + 40)]
    logger.info(
        "[PIIDEBUG] action=%s type=%s text=%r reason=%r | ctx_before=%r | ctx_after=%r",
        action,
        entity_type,
        matched_text,
        reason,
        before,
        after,
    )


def sensitivity_from_protected_types(pii_types: List[str]) -> float:
    """Orchestrator 와 동일 가중치이나 보호 대상만 반영."""
    weights = {
        "KR_RRN": 1.0,
        "KR_PASSPORT": 0.9,
        "KR_DRIVER_LICENSE": 0.8,
        "KR_BANK_ACCOUNT": 0.85,
        "KR_BRN": 0.6,
    }
    protected = filter_to_protected_pii_types(pii_types)
    if not protected:
        return 0.0
    base = max((weights.get(t, 0.3) for t in protected), default=0.0)
    if len(protected) > 1:
        base = min(1.0, base + 0.05 * (len(protected) - 1))
    return round(base, 4)
