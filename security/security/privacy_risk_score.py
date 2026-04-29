"""
security/privacy_risk_score.py
──────────────────────────────────────────────────────────────────────────────
Privacy Risk Score (PRS) — 설명 가능한 규칙 기반 리스크 스코어링 알고리즘.

논문 연결:
  "Mitigating Privacy Risks in Retrieval-Augmented Generation via
   Locally Private Entity Perturbation" 의 엔티티 위험 분류 개념을
  가중합 스코어링으로 구체화.

수식:
  PRS = w_q * QueryRisk
      + w_p * PIIDensity
      + w_e * ExposureRisk
      + w_b * BulkIntent

피처 정의:
  QueryRisk    (0.0 또는 1.0): _QUERY_KW_SCORES 키가 질의에 하나라도 포함되면 1.0
                              (w_q=0.3 곱해 PRS≥NORMAL 임계에 도달하도록 캘리브)
  PIIDensity   (0.0~1.0): 검색된 청크 중 PII 포함 비율 (feature_map.pii_chunk_ratio)
  ExposureRisk (0.0~1.0): PII 유형별 최대 위험 가중치 (feature_map.pii_types)
  BulkIntent   (0.0~1.0): 대량 추출 신호 (feature_map.bulk_request + 키워드)

분류 임계값 (config에서 조정):
  PRS < PRS_NORMAL_THRESHOLD    → NORMAL
  PRS < PRS_DANGEROUS_THRESHOLD → SENSITIVE
  PRS ≥ PRS_DANGEROUS_THRESHOLD → DANGEROUS

디버깅:
  PRSResult.breakdown 딕셔너리에 각 피처값 포함
  → logger에 출력하면 어느 피처가 점수를 올렸는지 즉시 확인 가능
  → 임계값 조정 시 config.py 에서만 변경, 이 파일 수정 불필요

ABC: [A] 보안 분류만 담당. DB·UI·외부통신 없음.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 가중치 (튜닝 포인트)
# ──────────────────────────────────────────────────────────────────────────────

# PRS 수식 가중치 합이 1.0 이 되도록 설정
_W_QUERY_RISK    = 0.30
_W_PII_DENSITY   = 0.25
_W_EXPOSURE_RISK = 0.30
_W_BULK_INTENT   = 0.15

# 질문 키워드 위험 점수 (0.0~1.0)
_QUERY_KW_SCORES: Dict[str, float] = {
    # DANGEROUS 수준 키워드 (0.8+)
    "전부":       0.85, "모두":        0.85, "전체 출력":  0.90,
    "dump":       0.90, "export":      0.85, "삭제":       0.80,
    "all records":0.90, "raw data":    0.85, "원문 전부":  0.90,
    "개인정보 전부":0.90,
    # SENSITIVE 수준 키워드 (0.5~0.75)
    "주민번호":   0.75, "계좌번호":    0.70, "비밀번호":   0.65,
    "카드번호":   0.70, "패스워드":    0.65, "여권":        0.60,
    "passport":   0.60, "운전면허":    0.60,     "사업자번호":  0.55,
    "사업자등록": 0.55, "개인정보":    0.70,
    # 전화·이메일은 비민감 정책: 질의 키워드 위험도에 반영하지 않음
}

# PII 유형별 노출 위험 가중치 (ExposureRisk 계산용)
_PII_EXPOSURE_WEIGHTS: Dict[str, float] = {
    "KR_RRN":            1.00,
    "KR_PASSPORT":       0.90,
    "KR_DRIVER_LICENSE": 0.80,
    "KR_BANK_ACCOUNT":   0.85,
    "KR_BRN":            0.60,
    "CREDIT_CARD":       0.88,
    # 전화번호는 비민감 정책: PRS 노출 위험도에서 제외 수준으로 낮춤
    "KR_PHONE":          0.00,
    "PERSON":            0.40,
    "EMAIL_ADDRESS":     0.00,
    "PHONE_NUMBER":      0.00,
}

# BulkIntent 키워드 (존재만 해도 BulkIntent = 1.0)
_BULK_KW = frozenset([
    "전부", "모두", "전체 출력", "dump", "export", "all records",
    "raw data", "원문 전부", "개인정보 전부", "삭제",
])


# ──────────────────────────────────────────────────────────────────────────────
# 결과 타입
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PRSResult:
    """Privacy Risk Score 계산 결과."""
    score: float                     # 최종 PRS (0.0~1.0)
    label: str                       # "NORMAL" | "SENSITIVE" | "DANGEROUS"
    breakdown: Dict[str, float] = field(default_factory=dict)
    reason: str = ""

    def __str__(self) -> str:  # 디버깅용
        bd = ", ".join(f"{k}={v:.3f}" for k, v in self.breakdown.items())
        return f"PRS={self.score:.3f} [{self.label}] ({bd}) — {self.reason}"


# ──────────────────────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────────────────────

def compute_prs(
    user_query: str,
    feature_map: Dict[str, Any],
) -> PRSResult:
    """
    쿼리와 feature_map 으로 Privacy Risk Score 를 계산한다.

    Args:
        user_query:  사용자 원문 질의
        feature_map: RetrievalAgent가 반환한 피처 딕셔너리
                     {contains_pii, bulk_request, pii_types, pii_chunk_ratio, ...}

    Returns:
        PRSResult (score, label, breakdown, reason)
    """
    q = user_query.lower()

    # ── 1. QueryRisk ─────────────────────────────────────────────────────────
    # 키워드별 점수는 '매칭 여부' 판별에만 쓰고, 실제 QueryRisk 는 이진(0 또는 1)로 둔다.
    # 이유: w_q=0.3 이므로 (예) "여권" 0.6 → 0.3*0.6=0.18 < PRS_NORMAL_THRESHOLD(0.3)
    #      이 되어 민감 질의가 NORMAL 로 떨어지는 캘리브 오류를 막는다.
    matched_kw_scores = [
        score for kw, score in _QUERY_KW_SCORES.items()
        if kw in q and score > 0.0
    ]
    if matched_kw_scores:
        query_risk = 1.0
    else:
        query_risk = 0.0

    # ── 2. PIIDensity ────────────────────────────────────────────────────────
    pii_density = float(feature_map.get("pii_chunk_ratio", 0.0))
    # 단순 contains_pii 신호도 반영 (비율 정보 없을 때 대체)
    if pii_density == 0.0 and feature_map.get("contains_pii"):
        pii_density = 0.5

    # ── 3. ExposureRisk ──────────────────────────────────────────────────────
    pii_types: List[str] = feature_map.get("pii_types") or []
    if pii_types:
        exposure_risk = max(
            (_PII_EXPOSURE_WEIGHTS.get(t.upper(), 0.30) for t in pii_types),
            default=0.0,
        )
    else:
        exposure_risk = 0.0

    # ── 4. BulkIntent ────────────────────────────────────────────────────────
    bulk_from_kw = 1.0 if any(kw in q for kw in _BULK_KW) else 0.0
    bulk_intent  = max(bulk_from_kw, 1.0 if feature_map.get("bulk_request") else 0.0)

    # ── PRS 합산 ──────────────────────────────────────────────────────────────
    prs = (
        _W_QUERY_RISK    * query_risk
        + _W_PII_DENSITY   * pii_density
        + _W_EXPOSURE_RISK * exposure_risk
        + _W_BULK_INTENT   * bulk_intent
    )
    prs = round(min(1.0, max(0.0, prs)), 4)

    # 대량/유출 의도(_BULK_KW): w_q*1 + w_b*1 = 0.45 만 되어 DANGEROUS(0.65) 미만에 머무는 문제 보완
    if any(kw in q for kw in _BULK_KW):
        dangerous_thr0 = getattr(config, "PRS_DANGEROUS_THRESHOLD", 0.65)
        prs = max(prs, float(dangerous_thr0))

    # ── 분류 ─────────────────────────────────────────────────────────────────
    normal_thr    = getattr(config, "PRS_NORMAL_THRESHOLD",    0.30)
    dangerous_thr = getattr(config, "PRS_DANGEROUS_THRESHOLD", 0.65)

    if prs >= dangerous_thr:
        label  = "DANGEROUS"
        action = "block"
        reason = f"PRS={prs:.3f} ≥ {dangerous_thr} (위험 수준)"
    elif prs >= normal_thr:
        label  = "SENSITIVE"
        action = "confirm"
        reason = f"PRS={prs:.3f} ∈ [{normal_thr}, {dangerous_thr}) (민감 수준)"
    else:
        label  = "NORMAL"
        action = "allow"
        reason = f"PRS={prs:.3f} < {normal_thr} (일반 수준)"

    breakdown = {
        "QueryRisk":    round(query_risk, 4),
        "PIIDensity":   round(pii_density, 4),
        "ExposureRisk": round(exposure_risk, 4),
        "BulkIntent":   round(bulk_intent, 4),
    }

    result = PRSResult(score=prs, label=label, breakdown=breakdown, reason=reason)
    logger.debug("[PRS] %s", result)
    return result


def classify_by_prs(
    user_query: str,
    feature_map: Dict[str, Any],
):
    """
    PRS 계산 후 ClassificationResult 형식으로 반환.
    orchestrator.py 의 _rule_based_classify() 를 대체.

    Returns:
        security.qwen_classifier.ClassificationResult
    """
    from security.qwen_classifier import ClassificationResult

    prs_result = compute_prs(user_query, feature_map)
    action_map = {"NORMAL": "allow", "SENSITIVE": "confirm", "DANGEROUS": "block"}
    action = action_map.get(prs_result.label, "allow")

    return ClassificationResult(
        label=prs_result.label,
        reason=prs_result.reason,
        action=action,
    )
