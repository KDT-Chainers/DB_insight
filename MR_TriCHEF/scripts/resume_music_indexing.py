"""resume_music_indexing.py — Music SigLIP2 재인덱싱 재개 wrapper.

PowerShell 인라인 명령의 인용 이슈를 피하기 위한 독립 실행 스크립트.
registry 기반 증분 처리이므로 이미 완료된 1-6번은 건너뛰고 7-14만 처리.
"""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "MR_TriCHEF"))

from pipeline.music_runner import run_music_incremental

print("[resume_music] Music SigLIP2 재인덱싱 재개 (registry 기반 증분)...")
count = 0
for r in run_music_incremental(progress=print):
    count += 1
    # FileResult dataclass (rel_path, status, windows, duration, elapsed, reason)
    status = getattr(r, "status", "?")
    rel = getattr(r, "rel_path", "?")
    wins = getattr(r, "windows", 0)
    elapsed = getattr(r, "elapsed", 0.0)
    reason = getattr(r, "reason", "")
    print("  [" + str(count) + "] " + str(status) + "  wins=" + str(wins)
          + "  " + str(round(elapsed, 1)) + "s  " + str(rel)
          + (("  reason=" + reason) if reason else ""))

print("\n[resume_music] 완료 — 총 " + str(count) + "개 처리")
