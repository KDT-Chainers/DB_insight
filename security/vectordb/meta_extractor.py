"""
vectordb/meta_extractor.py
──────────────────────────────────────────────────────────────────────────────
원본 청크에서 PII 메타데이터(값 없이 유형·문서 분류만)를 추출한다.

ABC Rule: [A] 신뢰불가 입력(청크 텍스트) 처리만 담당.
          [B] DB 접근 없음 / [C] 외부 통신 없음.

주의: 이 모듈은 PII 값(주민번호, 계좌번호 등 실제 숫자·문자열) 을
      절대로 반환 dict에 포함하지 않는다. 유형 이름과 민감도 점수만 허용.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

# ── PII 유형별 민감도 가중치 ───────────────────────────────────────────────────
_PII_WEIGHT: Dict[str, float] = {
    "KR_RRN": 1.0,              # 주민등록번호
    "KR_PASSPORT": 0.9,         # 여권
    "KR_DRIVER_LICENSE": 0.8,   # 운전면허
    "KR_BANK_ACCOUNT": 0.85,    # 계좌번호
    "KR_BRN": 0.6,              # 사업자등록번호
    "PERSON": 0.4,
    "EMAIL_ADDRESS": 0.5,
    "PHONE_NUMBER": 0.6,
    "LOCATION": 0.3,
    "DATE_TIME": 0.1,
}

# ── 문서 유형 추론 규칙 ────────────────────────────────────────────────────────
# PII 유형 집합 → doc_type 이름
_DOC_TYPE_RULES: List[tuple[frozenset, str]] = [
    (frozenset({"KR_PASSPORT"}),                    "passport"),
    (frozenset({"KR_RRN"}),                         "rrn_document"),
    (frozenset({"KR_DRIVER_LICENSE"}),               "driver_license"),
    (frozenset({"KR_BANK_ACCOUNT"}),                 "bank_document"),
    (frozenset({"KR_BRN"}),                         "business_registration"),
    (frozenset({"PERSON", "EMAIL_ADDRESS"}),         "personal_contact"),
    (frozenset({"PHONE_NUMBER"}),                   "contact_info"),
]

# 키워드 기반 문서 유형 추론 (PII 없어도 텍스트 내용으로 분류)
_KEYWORD_DOC_TYPE: List[tuple[list[str], str]] = [
    (["여권", "passport", "mrz", "nationality"],    "passport"),
    (["주민등록", "주민번호", "rrn"],                 "rrn_document"),
    (["운전면허", "driver", "면허번호"],              "driver_license"),
    (["계좌", "account", "은행", "bank"],            "bank_document"),
    (["사업자등록", "사업자번호", "brn"],              "business_registration"),
    (["회의", "meeting", "minutes", "agenda"],       "meeting"),
    (["계약", "contract", "agreement"],              "contract"),
    (["보고서", "report", "분석"],                   "report"),
]

# ── 검증 함수 ─────────────────────────────────────────────────────────────────

# PII 값처럼 보이는 패턴: 숫자 6자리 이상, 하이픈 포함 숫자열 등
_PII_VALUE_PATTERN = re.compile(
    r"\b\d{6,}\b"           # 6자리 이상 숫자
    r"|\b[A-Z]\d{8}\b"      # 여권번호 형태
    r"|\b\d{3}-\d{2}-\d{5}\b"  # 주민번호 형태
    r"|\b\d{4}-\d{4}-\d{4}\b"  # 계좌 형태
)


def _validate_meta(meta: Dict[str, Any]) -> None:
    """
    메타데이터에 PII 값이 포함되어 있는지 검증한다.
    의심스러운 패턴이 발견되면 ValueError를 발생시켜 저장을 중단한다.

    검사 대상 필드: doc_type, pii_types (값이 아닌 유형 이름인지 확인)
    """
    forbidden_fields = {"rrn_value", "passport_number", "account_number",
                        "phone", "email", "name", "address"}
    for key in meta.keys():
        if key.lower() in forbidden_fields:
            raise ValueError(f"[meta_extractor] 금지 필드 '{key}' 포함 — PII 값 저장 차단")

    # pii_types는 리스트여야 하고, 각 원소는 유형 이름 문자열(숫자 없음)이어야 함
    pii_types = meta.get("pii_types", [])
    if not isinstance(pii_types, list):
        raise TypeError("[meta_extractor] pii_types는 리스트여야 합니다")

    for t in pii_types:
        if not isinstance(t, str):
            raise TypeError(f"[meta_extractor] pii_types 원소는 문자열이어야 합니다: {t!r}")
        if _PII_VALUE_PATTERN.search(t):
            raise ValueError(
                f"[meta_extractor] pii_types 원소에 PII 값 의심 패턴 포함: '{t}' — 저장 차단"
            )


# ── 공개 API ──────────────────────────────────────────────────────────────────

def extract_meta(
    chunk_text: str,
    pii_findings: list,
    chunk_id: str = "",
) -> Dict[str, Any]:
    """
    청크 텍스트와 PII 탐지 결과에서 메타데이터만 추출한다.

    반환 형식:
        {
            "chunk_id":         str,
            "doc_type":         str,       # "passport", "bank", "meeting" 등
            "pii_types":        list[str], # ["KR_PASSPORT"] — 값 자체는 절대 포함 금지
            "has_pii":          bool,
            "sensitivity_score":float      # 0.0 ~ 1.0
        }

    Args:
        chunk_text:   원본 청크 텍스트 (PII 값 추출에 사용하지 않음)
        pii_findings: PIIDetector.scan_chunks() 의 ChunkScanResult.findings 리스트
        chunk_id:     청크 고유 식별자
    """
    # PII 유형 이름만 수집 (실제 값인 .text 필드는 무시)
    pii_types: List[str] = []
    for finding in pii_findings:
        entity = getattr(finding, "entity_type", None) or finding.get("entity_type", "")
        if entity and entity not in pii_types:
            pii_types.append(entity)

    has_pii = bool(pii_types)

    # 문서 유형 추론 — PII 유형 기반
    doc_type = _infer_doc_type_from_pii(set(pii_types))

    # 문서 유형 추론 — 텍스트 키워드 기반 (PII가 없거나 유형으로 판단 불가 시)
    if doc_type == "unknown":
        doc_type = _infer_doc_type_from_keywords(chunk_text)

    # 민감도 점수 계산
    sensitivity_score = _calc_sensitivity(pii_types, doc_type)

    meta = {
        "chunk_id":          chunk_id,
        "doc_type":          doc_type,
        "pii_types":         pii_types,
        "has_pii":           has_pii,
        "sensitivity_score": round(sensitivity_score, 4),
    }

    # 저장 전 PII 값 포함 여부 최종 검증
    _validate_meta(meta)

    return meta


def build_meta_embedding_text(meta: Dict[str, Any]) -> str:
    """
    meta_index에 저장할 임베딩용 텍스트를 생성한다.
    실제 PII 값 없이 문서 유형과 PII 유형 이름만으로 구성.

    예: "여권 passport 개인정보 PII 민감문서 KR_PASSPORT"
    """
    parts: List[str] = []

    doc_type = meta.get("doc_type", "unknown")
    parts.extend(_DOC_TYPE_KOREAN_TERMS.get(doc_type, [doc_type]))

    for pii_type in meta.get("pii_types", []):
        parts.append(pii_type)
        parts.extend(_PII_KOREAN_TERMS.get(pii_type, []))

    if meta.get("has_pii"):
        parts.extend(["개인정보", "PII", "민감문서"])

    return " ".join(parts)


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

_DOC_TYPE_KOREAN_TERMS: Dict[str, List[str]] = {
    "passport":              ["여권", "passport", "여권번호", "여권사진", "해외여행"],
    "rrn_document":          ["주민등록", "주민번호", "주민등록증"],
    "driver_license":        ["운전면허", "면허증", "driver"],
    "bank_document":         ["계좌", "은행", "bank", "account", "금융"],
    "business_registration": ["사업자등록증", "사업자번호", "법인"],
    "personal_contact":      ["연락처", "이름", "이메일", "contact"],
    "contact_info":          ["전화번호", "연락처", "phone"],
    "meeting":               ["회의", "meeting", "agenda", "회의록"],
    "contract":              ["계약", "contract", "agreement", "계약서"],
    "report":                ["보고서", "report", "분석", "통계"],
}

_PII_KOREAN_TERMS: Dict[str, List[str]] = {
    "KR_PASSPORT":       ["여권", "passport", "여권번호"],
    "KR_RRN":            ["주민번호", "주민등록번호"],
    "KR_DRIVER_LICENSE": ["운전면허", "면허번호"],
    "KR_BANK_ACCOUNT":   ["계좌번호", "통장번호"],
    "KR_BRN":            ["사업자번호", "사업자등록번호"],
    "PERSON":            ["이름", "성명"],
    "EMAIL_ADDRESS":     ["이메일", "email"],
    "PHONE_NUMBER":      ["전화번호", "휴대폰"],
}


def _infer_doc_type_from_pii(pii_type_set: set) -> str:
    """PII 유형 집합으로 문서 유형 추론"""
    for required, doc_type in _DOC_TYPE_RULES:
        if required.issubset(pii_type_set):
            return doc_type
    return "unknown"


def _infer_doc_type_from_keywords(text: str) -> str:
    """텍스트 키워드로 문서 유형 추론"""
    text_lower = text.lower()
    for keywords, doc_type in _KEYWORD_DOC_TYPE:
        if any(kw in text_lower for kw in keywords):
            return doc_type
    return "unknown"


def _calc_sensitivity(pii_types: List[str], doc_type: str) -> float:
    """PII 유형과 문서 유형 기반 민감도 점수 계산 (0.0 ~ 1.0)"""
    if not pii_types:
        return 0.0
    score = max((_PII_WEIGHT.get(t, 0.3) for t in pii_types), default=0.0)
    # 복수 PII 유형이면 소폭 가중
    if len(pii_types) > 1:
        score = min(1.0, score + 0.05 * (len(pii_types) - 1))
    return score
