"""npy/ids/segments 증분 append 헬퍼."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def append_npy(path: Path, new: np.ndarray) -> int:
    """기존 .npy 와 vstack 후 저장. 반환: 총 행 수."""
    if path.exists():
        prev = np.load(path)
        if prev.size == 0:
            merged = new
        elif prev.shape[1] != new.shape[1]:
            raise ValueError(f"dim mismatch: {prev.shape} vs {new.shape} @ {path.name}")
        else:
            merged = np.vstack([prev, new])
    else:
        merged = new
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, merged.astype(np.float32))
    return int(merged.shape[0])


def append_ids(path: Path, new_ids: list[str]) -> int:
    prev: list[str] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            prev = data.get("ids", [])
        except Exception:
            prev = []
    all_ids = prev + new_ids
    path.write_text(
        json.dumps({"ids": all_ids}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(all_ids)


def append_segments(path: Path, new_segs: list[dict]) -> int:
    prev: list[dict] = []
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(prev, list):
                prev = []
        except Exception:
            prev = []
    merged = prev + new_segs
    path.write_text(
        json.dumps(merged, ensure_ascii=False),
        encoding="utf-8",
    )
    return len(merged)
