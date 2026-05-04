"""
security/regenerate_handler.py
──────────────────────────────────────────────────────────────────────────────
Security Critic 의 regenerate_with_constraints 결정 처리기.

역할:
    응답 텍스트에서 PII를 제거한 "안전한 버전"을 반환한다.
    원본 텍스트는 절대 수정하지 않는다 (사본에만 작업).

현재 구현:
    LLM 호출 없이 정규식으로 PII를 토큰 문자열로 치환.
    ex) "주민번호 900101-1234567 → 주민번호 [주민등록번호 제거됨]"

향후 확장:
    USE_QWEN=1 환경에서 Qwen 호출로 자연스럽게 재작성 가능.
    현재는 의도적으로 규칙 기반만 사용.

ABC: 생성·치환 출력만. DB·외부통신 없음.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# PII 제거 패턴 (치환 문자열 포함)
# ──────────────────────────────────────────────────────────────────────────────

_REMOVAL_RULES: List[tuple] = [
    # (정규식 패턴, 치환 문자열)
    # 주의: 한국어 문자는 \w 에 포함되므로 \b 대신 (?<!\d)/(?!\d) 사용
    (r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)",                                  "[주민등록번호 제거됨]"),
    (r"(?<![A-Z])[A-Z]\d{7,8}(?!\d)",                                   "[여권번호 제거됨]"),
    (r"(?<!\d)\d{2}-\d{2}-\d{6}-\d{2}(?!\d)",                           "[운전면허 제거됨]"),
    # 전화번호(010/02/지역번호) 형태는 제외하고 계좌번호만 치환
    (r"(?<!\d)(?!(?:01[0-9]|02|0[3-9]\d)[-\s])\d{3,4}[-\s]\d{2,4}[-\s]\d{4,6}(?:[-\s]\d{1,3})?(?!\d)", "[계좌번호 제거됨]"),
    (r"(?<!\d)\d{3}-\d{2}-\d{5}(?!\d)",                                  "[사업자번호 제거됨]"),
    (r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",              "[이메일 제거됨]"),
]


# ──────────────────────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────────────────────

def strip_pii_from_output(
    text: str,
    pii_types: Optional[List[str]] = None,
) -> str:
    """
    생성 출력에서 PII를 제거한 안전한 텍스트를 반환한다.

    Args:
        text:      원본 생성 응답 텍스트
        pii_types: 제거 대상 PII 유형 (현재 미사용, 향후 선택적 제거 지원용)

    Returns:
        PII 치환된 텍스트 (원본 불변, 사본 반환)

    Examples:
        >>> strip_pii_from_output("계좌: 123-456-7890123")
        "계좌: [계좌번호 제거됨]"
    """
    if not text:
        return text

    result = text
    removed_count = 0

    for pattern, replacement in _REMOVAL_RULES:
        new_result = re.sub(pattern, replacement, result)
        if new_result != result:
            removed_count += result.count(re.findall(pattern, result)[0]) if re.findall(pattern, result) else 0
            result = new_result
            logger.debug("[RegenerateHandler] 패턴 적용: %s → %s", pattern, replacement)

    if removed_count > 0 or result != text:
        logger.info("[RegenerateHandler] PII 제거 완료. 원본 길이=%d, 결과 길이=%d", len(text), len(result))

    return result


def build_regenerate_notice(constraints: Optional[str] = None) -> str:
    """
    regenerate_with_constraints 결정 시 UI에 표시할 안내 메시지를 반환한다.

    Args:
        constraints: Critic 에서 지정한 제약 조건 설명

    Returns:
        사용자 표시용 HTML 안내 문자열
    """
    base = "⚠️ 응답에 개인정보가 포함되어 있어 해당 정보를 제거했습니다."
    if constraints:
        return f"{base}\n제약: {constraints}"
    return base
