"""MR_TriCHEF/pipeline/sparse.py — BGE-M3 sparse lexical 채널 (DI 에서 포팅).

App/backend/embedders/trichef/bgem3_sparse.py 를 sys.path 추가로 재사용.
Movie/Music 의 STT 텍스트를 sparse 벡터로 인덱싱하여 lex 채널 추가.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2] / "App" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from embedders.trichef.bgem3_sparse import (  # noqa: E402,F401
    embed_query_sparse,
    lexical_scores,
)

try:
    from embedders.trichef.bgem3_sparse import embed_texts_sparse  # noqa: F401
except ImportError:
    embed_texts_sparse = None  # 원본 API 명명에 따라 noop
