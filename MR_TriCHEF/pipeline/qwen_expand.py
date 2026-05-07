"""MR_TriCHEF/pipeline/qwen_expand.py — 쿼리 확장(의역·동의어) 모듈.

DI 의 services/trichef/qwen_expand.py 재사용.
search.py 에서 쿼리 전처리 후 Re/Im 임베딩에 사용 가능.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2] / "App" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.trichef.qwen_expand import (  # noqa: E402,F401
    avg_normalize,
    expand,
)
