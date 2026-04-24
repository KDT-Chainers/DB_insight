"""run_calibration.py — calibration.py 독립 실행 wrapper.

calibration.py 는 패키지 내 상대 import 사용으로 직접 실행 불가.
이 스크립트가 sys.path 를 설정한 뒤 recalibrate() 를 호출한다.

실행:
    python MR_TriCHEF/scripts/run_calibration.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "MR_TriCHEF"))

from pipeline.calibration import recalibrate

print("[calibration] Movie + Music null 분포 재측정 시작...")
result = recalibrate()

print("\n[calibration] 결과:")
for domain, d in result.items():
    if d.get("status") == "ok":
        print(f"  {domain}: mu={d['mu_null']:.4f}  sigma={d['sigma_null']:.4f}"
              f"  thr={d.get('abs_threshold', d.get('p95', 0)):.4f}"
              f"  n={d['n']}")
    else:
        print(f"  {domain}: {d}")

print("\n[calibration] 완료 — _calibration.json 저장됨")
