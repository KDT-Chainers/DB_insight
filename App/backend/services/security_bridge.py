"""services/security_bridge.py — App/backend ↔ DB_insight/security 도킹 어댑터.

`security/` 패키지를 sys.path에 등록해 SecurityCritic을 직접 import하고,
LLM 출력 라우트가 호출하기 좋은 얇은 헬퍼 3종을 노출한다.

설계 원칙:
  - fail-open: 보안 모듈 import/호출 실패 시 통과 + ERROR 로그
  - 싱글턴: 매 호출마다 인스턴스 새로 만들지 않음
  - DB·외부 IO 없음: 정규식·메모리 위주 → 스트림 가드에 부담 없음

노출 함수:
  - quick_pii_scan(text)         : 스트림 누적 버퍼용 빠른 정규식 (보호 PII만)
  - review_final(query, output, session_id) -> dict : 종료 직전 최종 심사
  - mask_pii(text, types)        : strip_pii_from_output 위임 (마스킹)
"""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── security/ 패키지 sys.path 등록 ────────────────────────────────────────────
# App/backend/services/security_bridge.py → ../../../security
_SECURITY_ROOT = Path("C:/Honey/DB_insight/security").resolve()
if str(_SECURITY_ROOT) not in sys.path:
    sys.path.insert(0, str(_SECURITY_ROOT))

# ── lazy import + 싱글턴 ─────────────────────────────────────────────────────
_lock = threading.Lock()
_critic: Any = None
_engine: Any = None
_strip_fn: Any = None
_init_failed: bool = False


def _ensure_loaded() -> bool:
    """첫 호출 시 SecurityCritic / SessionRiskEngine 로드. 실패 시 False."""
    global _critic, _engine, _strip_fn, _init_failed
    if _init_failed:
        return False
    if _critic is not None and _engine is not None:
        return True
    with _lock:
        if _init_failed:
            return False
        if _critic is not None and _engine is not None:
            return True
        try:
            from security.security_critic import SecurityCritic        # type: ignore
            from security.session_risk_engine import SessionRiskEngine  # type: ignore
            from security.regenerate_handler import strip_pii_from_output  # type: ignore
            _critic = SecurityCritic()
            _engine = SessionRiskEngine()
            _strip_fn = strip_pii_from_output
            logger.info("[security_bridge] SecurityCritic loaded from %s", _SECURITY_ROOT)
            return True
        except Exception as e:
            _init_failed = True
            logger.error("[security_bridge] SecurityCritic 로드 실패 → fail-open: %s", e)
            return False


# ── 빠른 PII 스캔 (스트림 가드용) ────────────────────────────────────────────
import re as _re

# SecurityCritic._OUTPUT_PII_PATTERNS 와 동일한 보호 PII 패턴.
# 스트림 도중에는 컨텍스트 단어가 부분 도착할 수 있어 KR_BANK_ACCOUNT의 문맥 검사는 생략하지 않는다 →
# false positive 방지를 위해 KR_BANK_ACCOUNT는 review_final 단계로 미루고, 여기선 명백히
# 식별 가능한 패턴(주민/여권/면허/사업자/카드)만 본다.
_QUICK_PII_PATTERNS: List[tuple[str, str]] = [
    ("KR_RRN",            r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)"),
    ("KR_PASSPORT",       r"(?<![A-Z])[A-Z]\d{7,8}(?!\d)"),
    ("KR_DRIVER_LICENSE", r"(?<!\d)\d{2}-\d{2}-\d{6}-\d{2}(?!\d)"),
    ("KR_BRN",            r"(?<!\d)\d{3}-\d{2}-\d{5}(?!\d)"),
    ("CREDIT_CARD",
     r"(?<!\d)(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|"
     r"6(?:011|5[0-9]{2})[0-9]{12})(?!\d)"),
    ("CREDIT_CARD",       r"(?<!\d)(?:\d{4}[-\s]){3}\d{4}(?!\d)"),
]


def quick_pii_scan(text: str) -> List[str]:
    """스트림 누적 텍스트에서 보호 PII를 빠르게 탐지. 발견된 라벨 목록 반환."""
    if not text:
        return []
    found: List[str] = []
    for label, pattern in _QUICK_PII_PATTERNS:
        if _re.search(pattern, text):
            if label not in found:
                found.append(label)
    return found


# ── 최종 심사 ─────────────────────────────────────────────────────────────────
def review_final(
    user_query: str,
    generated_output: str,
    session_id: str = "default",
) -> Dict[str, Any]:
    """종료 직전 SecurityCritic 1회 심사. 항상 dict 반환 (fail-open)."""
    if not _ensure_loaded():
        return {"decision": "approve", "action": "show", "reason": "critic 미로드 (fail-open)",
                "pii_found_in_output": [], "constraints": None, "risk_score": 0,
                "ok": True, "blocked": False, "masked": False}
    try:
        state = _engine.get_state(session_id)
        decision = _critic.review(
            user_query=user_query or "",
            generated_output=generated_output or "",
            feature_map={},  # Phase 2에서 채움
            session_state=state,
        )
        d = decision.to_dict()
        d["ok"] = decision.is_approved
        d["blocked"] = decision.is_blocked
        d["masked"] = (decision.action == "mask")
        d["needs_regenerate"] = decision.needs_regenerate
        return d
    except Exception as e:
        logger.error("[security_bridge] review_final 실패 → fail-open: %s", e)
        return {"decision": "approve", "action": "show", "reason": f"critic 오류 (fail-open): {e}",
                "pii_found_in_output": [], "constraints": None, "risk_score": 0,
                "ok": True, "blocked": False, "masked": False}


def mask_pii(text: str, pii_types: Optional[List[str]] = None) -> str:
    """탐지된 PII를 마스킹. 실패 시 원문 반환."""
    if not text:
        return text
    if not _ensure_loaded() or _strip_fn is None:
        return text
    try:
        return _strip_fn(text, pii_types=pii_types or [])
    except Exception as e:
        logger.error("[security_bridge] mask_pii 실패 → 원문 반환: %s", e)
        return text
