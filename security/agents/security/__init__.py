"""
Security domain facade package.

도메인 분리를 위해 orchestrator는 이 패키지만 import한다.
내부 구현 파일 위치 변경 시에도 orchestrator 수정이 최소화된다.
"""

from .critic_domain import (
    CriticDecision,
    SecurityCritic,
    SessionRiskEngine,
    strip_pii_from_output,
)

