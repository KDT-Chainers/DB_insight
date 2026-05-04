"""
korean_recognizers.py
──────────────────────────────────────────────────────────────────────────────
한국형 개인정보 탐지를 위한 커스텀 Presidio Recognizer 모음.

탐지 대상:
  - 주민등록번호 (7자리 앞+7자리 뒤, 체크섬 검증)
  - 여권번호 (M12345678 형식)
  - 운전면허번호 (12-34-567890-01 형식)
  - 한국 계좌번호 (하이픈 포함 숫자 패턴만 1차 후보; 최종 인정은 pii_detector
    에서 은행명/계좌 키워드 문맥 + 반복 제거 후처리로 수행)
  - 사업자등록번호 (000-00-00000, 체크섬 검증)

전화번호(KR_PHONE) Recognizer는 등록하지 않는다.
이 프로젝트 정책상 전화·이메일은 민감 PII로 취급하지 않음 (pii_detector 엔티티 목록에서도 제외).

모두 1차 정규식 + (해당 시) 체크섬 검증 방식.
"""
from __future__ import annotations

import re
from typing import List, Optional

from presidio_analyzer import Pattern, PatternRecognizer

from security.pii_filter_helpers import ACCOUNT_KEYWORDS_FOR_CONTEXT, BANK_NAMES_FOR_CONTEXT


# ──────────────────────────────────────────────────────────────────────────────
# 체크섬 검증 헬퍼
# ──────────────────────────────────────────────────────────────────────────────

def _rrn_checksum(digits: str) -> bool:
    """
    주민등록번호 13자리 체크섬 검증.
    https://ko.wikipedia.org/wiki/주민등록번호
    """
    if len(digits) != 13 or not digits.isdigit():
        return False
    weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    total = sum(int(d) * w for d, w in zip(digits[:12], weights))
    check = (11 - (total % 11)) % 10
    return check == int(digits[12])


def _brn_checksum(digits: str) -> bool:
    """
    사업자등록번호 10자리 체크섬 검증.
    https://www.nts.go.kr
    """
    if len(digits) != 10 or not digits.isdigit():
        return False
    weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    total = sum(int(d) * w for d, w in zip(digits[:9], weights))
    total += int(digits[8]) * 5 // 10
    check = (10 - (total % 10)) % 10
    return check == int(digits[9])


# ──────────────────────────────────────────────────────────────────────────────
# 1. 주민등록번호
# ──────────────────────────────────────────────────────────────────────────────

class KoreanRRNRecognizer(PatternRecognizer):
    """주민등록번호: YYMMDD-GNNNNNN 또는 연속 13자리"""

    PATTERNS = [
        Pattern(
            name="rrn_with_hyphen",
            regex=r"\b(\d{6})-([1-4]\d{6})\b",
            score=0.9,
        ),
        Pattern(
            name="rrn_no_hyphen",
            regex=r"\b(\d{6})([1-4]\d{6})\b",
            score=0.6,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="KR_RRN",
            patterns=self.PATTERNS,
            supported_language="ko",
        )

    def validate_result(self, pattern_text: str) -> Optional[bool]:  # type: ignore[override]
        digits = re.sub(r"\D", "", pattern_text)
        return _rrn_checksum(digits)


# ──────────────────────────────────────────────────────────────────────────────
# 2. 여권번호
# ──────────────────────────────────────────────────────────────────────────────

class KoreanPassportRecognizer(PatternRecognizer):
    """여권번호: 알파벳 1자리 + 숫자 8자리 (예: M12345678)"""

    PATTERNS = [
        Pattern(
            name="passport",
            regex=r"\b[A-Z][0-9]{8}\b",
            score=0.8,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="KR_PASSPORT",
            patterns=self.PATTERNS,
            supported_language="ko",
        )


# ──────────────────────────────────────────────────────────────────────────────
# 3. 운전면허번호
# ──────────────────────────────────────────────────────────────────────────────

class KoreanDriverLicenseRecognizer(PatternRecognizer):
    """운전면허번호: 지역(2자리)-연도(2자리)-번호(6자리)-검증(2자리)"""

    PATTERNS = [
        Pattern(
            name="driver_license",
            regex=r"\b\d{2}-\d{2}-\d{6}-\d{2}\b",
            score=0.85,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="KR_DRIVER_LICENSE",
            patterns=self.PATTERNS,
            supported_language="ko",
        )


# ──────────────────────────────────────────────────────────────────────────────
# 4. 계좌번호 (은행별 길이 패턴)
# ──────────────────────────────────────────────────────────────────────────────

class KoreanBankAccountRecognizer(PatternRecognizer):
    """
    한국 계좌번호 1차 후보: 하이픈 포함 숫자 블록만.

    연속 10~14자리 숫자만 있는 패턴은 제거했다(보고서·표·발간번호 오탐 다수).
    최종적으로는 pii_detector 에서
      - 은행명 또는 계좌 관련 키워드가 주변에 있는지
      - 동일 값이 과도 반복되는지
    를 검사해 KR_BANK_ACCOUNT 로 확정한다.
    """

    PATTERNS = [
        Pattern(
            name="account_with_hyphen",
            regex=r"\b\d{3,4}-\d{2,6}-\d{4,7}(?:-\d{1,3})?\b",
            score=0.75,
        ),
    ]

    # Presidio 가 주변에서 찾으면 점수를 올려 주는 힌트(후처리 문맥 검사와 별개)
    CONTEXT = list(BANK_NAMES_FOR_CONTEXT) + list(ACCOUNT_KEYWORDS_FOR_CONTEXT)

    def __init__(self) -> None:
        super().__init__(
            supported_entity="KR_BANK_ACCOUNT",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            supported_language="ko",
        )


# ──────────────────────────────────────────────────────────────────────────────
# 5. 사업자등록번호
# ──────────────────────────────────────────────────────────────────────────────

class KoreanBRNRecognizer(PatternRecognizer):
    """사업자등록번호: 000-00-00000"""

    PATTERNS = [
        Pattern(
            name="brn",
            regex=r"\b\d{3}-\d{2}-\d{5}\b",
            score=0.9,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="KR_BRN",
            patterns=self.PATTERNS,
            supported_language="ko",
        )

    def validate_result(self, pattern_text: str) -> Optional[bool]:  # type: ignore[override]
        digits = re.sub(r"\D", "", pattern_text)
        return _brn_checksum(digits)


# ──────────────────────────────────────────────────────────────────────────────
# 6. 한국 전화번호 — 이 프로젝트에서는 Recognizer 로 등록하지 않음
#    (정책: 전화·이메일은 민감 PII 아님, pii_detector DEFAULT_ENTITIES 에서도 제외)
# ──────────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# 전체 커스텀 Recognizer 목록 (pii_detector 에서 임포트)
# ──────────────────────────────────────────────────────────────────────────────

ALL_KOREAN_RECOGNIZERS: List[PatternRecognizer] = [
    KoreanRRNRecognizer(),
    KoreanPassportRecognizer(),
    KoreanDriverLicenseRecognizer(),
    KoreanBankAccountRecognizer(),
    KoreanBRNRecognizer(),
]
