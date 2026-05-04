"""
policy.py
──────────────────────────────────────────────────────────────────────────────
검색 보안 정책 정의 및 실행.

NORMAL    → 즉시 검색, 관련 청크 반환, 답변 생성
SENSITIVE → 마스킹 미리보기 출력, [전체 보기] 클릭 시 추가 확인
DANGEROUS → 차단, 이유 반환

이 모듈은 Feature Map 과 분류 결과만 다루며
실제 원문 데이터를 조회하거나 변경하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────────────
# 정책 결과 타입
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PolicyDecision:
    """보안 정책 판단 결과"""
    allow:          bool
    require_confirm: bool          # [전체 보기] 확인이 필요한가
    block_reason:   Optional[str]  # 차단 시 이유
    masked_preview: bool           # 마스킹 미리보기 먼저 보여줄지
    log_event:      str            # 감사 로그에 남길 이벤트 설명


# ──────────────────────────────────────────────────────────────────────────────
# 정책 엔진
# ──────────────────────────────────────────────────────────────────────────────

class SecurityPolicy:
    """
    label 과 feature_map 을 받아 PolicyDecision 을 반환.

    ABC 원칙 준수:
      - 신뢰불가 입력(label)을 처리하지만 이미 QwenClassifier 에서 전처리됨
      - DB 접근 없음
      - 상태 변경 없음 (로그 기록은 Audit Logger 에 위임)
    """

    def evaluate(
        self,
        label: str,
        feature_map: Dict[str, Any],
    ) -> PolicyDecision:
        """
        Args:
            label: "NORMAL" | "SENSITIVE" | "DANGEROUS"
            feature_map: Retrieval Engine 생성 Feature Map

        Returns:
            PolicyDecision
        """
        label = label.upper()

        if label == "NORMAL":
            return self._normal_policy(feature_map)
        elif label == "SENSITIVE":
            return self._sensitive_policy(feature_map)
        elif label == "DANGEROUS":
            return self._dangerous_policy(feature_map)
        else:
            # 알 수 없는 레이블은 안전하게 차단
            return PolicyDecision(
                allow=False,
                require_confirm=False,
                block_reason=f"알 수 없는 레이블: {label}",
                masked_preview=False,
                log_event="UNKNOWN_LABEL_BLOCKED",
            )

    # ── 개별 정책 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _normal_policy(feature_map: Dict[str, Any]) -> PolicyDecision:
        """
        NORMAL: 즉시 검색 허용.
        대량 요청(bulk_request=True) 시에는 확인 필요.
        """
        if feature_map.get("bulk_request", False):
            return PolicyDecision(
                allow=True,
                require_confirm=True,
                block_reason=None,
                masked_preview=False,
                log_event="NORMAL_BULK_CONFIRM",
            )
        return PolicyDecision(
            allow=True,
            require_confirm=False,
            block_reason=None,
            masked_preview=False,
            log_event="NORMAL_ALLOWED",
        )

    @staticmethod
    def _sensitive_policy(feature_map: Dict[str, Any]) -> PolicyDecision:
        """
        SENSITIVE: 마스킹 미리보기 먼저 출력.
        사용자가 [전체 보기] 클릭 시 원문 공개.
        """
        return PolicyDecision(
            allow=True,
            require_confirm=True,
            block_reason=None,
            masked_preview=True,
            log_event="SENSITIVE_MASKED_PREVIEW",
        )

    @staticmethod
    def _dangerous_policy(feature_map: Dict[str, Any]) -> PolicyDecision:
        """
        DANGEROUS: 차단.
        sensitivity_score 가 0.95 이상이면 더 강한 이유 표시.
        """
        score = feature_map.get("sensitivity_score", 0.0)
        reason = "대량 개인정보 요청 또는 위험 명령으로 차단되었습니다."
        if score >= 0.95:
            reason = "매우 높은 위험도로 요청이 차단되었습니다. (score={:.2f})".format(score)
        return PolicyDecision(
            allow=False,
            require_confirm=False,
            block_reason=reason,
            masked_preview=False,
            log_event="DANGEROUS_BLOCKED",
        )


# ──────────────────────────────────────────────────────────────────────────────
# 업로드 정책 (브레이크 모달 선택지)
# ──────────────────────────────────────────────────────────────────────────────

class UploadPolicy:
    """
    사용자가 브레이크 모달에서 선택한 옵션을 처리 방침으로 변환.

    브레이크 모달(PII 감지 알림)은 `PIIDetector`가 찾은 **정책 보호 PII**가
    있을 때만 뜬다. 보호 대상은 주민·여권·운전면허·계좌·사업자번호뿐이며,
    전화번호·이메일은 민감정보로 분류하지 않는다(security.pii_filter_helpers).
    """

    # 선택 옵션 상수
    MASK_AND_EMBED   = "mask_and_embed"
    SKIP_PII_CHUNKS  = "skip_pii_chunks"
    EMBED_ALL        = "embed_all"
    CANCEL           = "cancel"

    VALID_CHOICES = {MASK_AND_EMBED, SKIP_PII_CHUNKS, EMBED_ALL, CANCEL}

    @staticmethod
    def resolve(choice: str) -> Dict[str, Any]:
        """
        사용자 선택 → 백엔드 처리 지침 반환.

        Returns:
            dict with keys:
                proceed (bool): 임베딩 진행 여부
                mask (bool): 텍스트 마스킹 여부
                exclude_pii_chunks (bool): PII 청크 제외 여부
        """
        if choice == UploadPolicy.MASK_AND_EMBED:
            return {"proceed": True, "mask": True, "exclude_pii_chunks": False}
        elif choice == UploadPolicy.SKIP_PII_CHUNKS:
            return {"proceed": True, "mask": False, "exclude_pii_chunks": True}
        elif choice == UploadPolicy.EMBED_ALL:
            return {"proceed": True, "mask": False, "exclude_pii_chunks": False}
        else:  # CANCEL 또는 알 수 없음
            return {"proceed": False, "mask": False, "exclude_pii_chunks": False}
