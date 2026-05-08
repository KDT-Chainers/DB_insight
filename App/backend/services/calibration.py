"""
적응형 캘리브레이션 — 실제 처리 시간으로 index_estimator 계수를 점진 갱신.

저장: ~/.db_insight/calibration.json
EWMA α=0.15 : 천천히 적응 → 이상치(GPU 재시작, 냉각 스로틀 등)에 강건.

계수 구조:
  { "doc": {"base": float, "per_mb": float}, ... }
"""
from __future__ import annotations

import json
from pathlib import Path

_CALIB_PATH = Path.home() / ".db_insight" / "calibration.json"

_DEFAULTS: dict[str, dict] = {
    "doc":   {"base": 5.0, "per_mb": 1.0},
    "image": {"base": 0.4, "per_mb": 0.1},
    "video": {"base": 3.0, "per_mb": 0.5},
    "audio": {"base": 2.0, "per_mb": 0.8},
}

_ALPHA = 0.15  # EWMA 학습률


def load_coefs() -> dict[str, dict]:
    """저장된 캘리브레이션 계수 반환. 파일 없으면 기본값."""
    if _CALIB_PATH.exists():
        try:
            raw = json.loads(_CALIB_PATH.read_text(encoding="utf-8"))
            return {
                t: {
                    "base":   float(raw.get(t, {}).get("base",   d["base"])),
                    "per_mb": float(raw.get(t, {}).get("per_mb", d["per_mb"])),
                }
                for t, d in _DEFAULTS.items()
            }
        except Exception:
            pass
    return {t: d.copy() for t, d in _DEFAULTS.items()}


def update(measurements: list[dict]) -> None:
    """
    실측 데이터로 계수 EWMA 갱신 후 저장.

    measurements: [{"type": "image", "size_mb": 0.8, "actual_sec": 1.4}, ...]
    status == "done" 파일만 전달할 것. 이상치는 내부에서 필터링.
    """
    if not measurements:
        return

    coefs = load_coefs()
    changed = False

    by_type: dict[str, list[tuple[float, float]]] = {}
    for m in measurements:
        t = m.get("type")
        if t not in coefs:
            continue
        actual  = float(m.get("actual_sec", 0))
        size_mb = float(m.get("size_mb",   0))
        if actual < 0.05 or actual > 3600:
            continue
        by_type.setdefault(t, []).append((size_mb, actual))

    for t, samples in by_type.items():
        if not samples:
            continue
        avg_size = sum(s for s, _ in samples) / len(samples)
        avg_time = sum(a for _, a in samples) / len(samples)

        predicted = coefs[t]["base"] + coefs[t]["per_mb"] * avg_size
        if predicted <= 0:
            continue

        scale = max(0.1, min(10.0, avg_time / predicted))
        factor = 1 - _ALPHA + _ALPHA * scale
        coefs[t]["base"]   = round(coefs[t]["base"]   * factor, 4)
        coefs[t]["per_mb"] = round(coefs[t]["per_mb"] * factor, 4)
        changed = True

    if changed:
        _CALIB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CALIB_PATH.write_text(
            json.dumps(coefs, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
