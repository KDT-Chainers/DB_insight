"""embedders/trichef/caption_io.py — 캡션 파일 로드 + 페이지 인덱스 유틸 (M-1).

여러 스크립트/모듈에 산재했던 `_load_caption` 복사본 통합.
`.caption.json` (L1+L2+L3 조합) 우선, 없으면 `.txt` fallback.
"""
from __future__ import annotations

import json
from pathlib import Path


def load_caption(cap_dir: Path, stem: str) -> str:
    """캡션 디렉토리에서 stem 에 해당하는 텍스트를 로드.

    우선순위: <stem>.caption.json (L1+L2+L3) > <stem>.txt > "".
    """
    jp = cap_dir / f"{stem}.caption.json"
    tp = cap_dir / f"{stem}.txt"
    if jp.exists():
        try:
            d = json.loads(jp.read_text(encoding="utf-8"))
            parts = [d.get(k, "") for k in ("L1", "L2", "L3")]
            return " ".join(x for x in parts if x)
        except Exception:
            pass
    if tp.exists():
        return tp.read_text(encoding="utf-8")
    return ""


def page_idx_from_stem(page_stem: str) -> int:
    """`p0000` 형태 stem → 0. 'p' prefix 없어도 숫자 파싱."""
    s = page_stem[1:] if page_stem.startswith("p") else page_stem
    try:
        return int(s)
    except ValueError:
        return 0
