"""process_one_music.py — 단일 음원 파일 처리 (subprocess 격리용).

사용:
    python process_one_music.py <rel_path>

rel_path 는 MUSIC_RAW_DIR 기준 상대 경로 (registry key 형식).
해당 파일이 이미 인덱싱되어 있으면 skip. 아니면 SigLIP2 재인덱싱 1개 수행.
크래시 시 프로세스 종료코드 != 0.
"""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "MR_TriCHEF"))

from pipeline.music_runner import run_music_incremental
from pipeline.paths import MUSIC_RAW_DIR


def main():
    if len(sys.argv) < 2:
        print("usage: process_one_music.py <rel_path>")
        return 2
    target_rel = sys.argv[1].replace("\\", "/")

    # run_music_incremental 은 전체 순회하되 대상 외 파일은 skip 되어 빠르게 통과.
    # 대상 1개만 실제 처리하고 즉시 종료.
    processed = False
    for r in run_music_incremental(progress=print):
        rel = getattr(r, "rel_path", "")
        status = getattr(r, "status", "?")
        if rel == target_rel:
            processed = True
            print("[process_one] target " + status + "  " + rel)
            return 0 if status in ("done", "skipped") else 1
        # 대상 이전 파일은 skip 이어야 효율적. done 이면 registry 갱신됨(정상).
    if not processed:
        print("[process_one] target not found: " + target_rel)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
