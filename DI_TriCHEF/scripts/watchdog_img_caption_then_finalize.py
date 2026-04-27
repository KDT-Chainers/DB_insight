"""Img 3-stage caption 완료를 폴링하고 후속 2단계 자동 실행.

체인:
  1) 10분 간격으로 _caption_triple_progress.json 의 완료 개수 확인
  2) registry.json 총 개수와 일치하면 다음 단계로 이행
  3) build_img_caption_triple.py --embed-only  → L1/L2/L3 cache 생성
  4) recalibrate_query_null.py                 → image 도메인 fusion 공간 재보정

Claude Code 세션 종료/절전과 무관하게 독립 프로세스로 생존.
중단 시 재실행해도 동일 결과 (idempotent).

실행:
  python DI_TriCHEF/scripts/watchdog_img_caption_then_finalize.py
  # 또는 Windows:
  start /B python DI_TriCHEF/scripts/watchdog_img_caption_then_finalize.py > watchdog.log 2>&1
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
IMG_DIR  = ROOT / "Data" / "embedded_DB" / "Img"
PROG     = IMG_DIR / "_caption_triple_progress.json"
REG      = IMG_DIR / "registry.json"
DONE_FLAG = IMG_DIR / "_watchdog_finalized.flag"

POLL_SEC = 600   # 10분

STEP_EMBED = [
    sys.executable,
    str(ROOT / "DI_TriCHEF" / "scripts" / "build_img_caption_triple.py"),
    "--embed-only",
]
STEP_RECAL = [
    sys.executable,
    str(ROOT / "scripts" / "recalibrate_query_null.py"),
]


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[watchdog {ts}] {msg}", flush=True)


def _count_done() -> int:
    if not PROG.exists():
        return 0
    try:
        return len(json.loads(PROG.read_text(encoding="utf-8")))
    except Exception:
        return 0


def _count_total() -> int:
    if not REG.exists():
        return -1
    try:
        return len(json.loads(REG.read_text(encoding="utf-8")))
    except Exception:
        return -1


def _run(cmd: list[str], stage: str) -> int:
    _log(f"── run: {stage} ──")
    _log(f"    cmd: {' '.join(cmd)}")
    p = subprocess.run(cmd, cwd=str(ROOT))
    _log(f"    exit: {p.returncode}")
    return p.returncode


def main() -> None:
    if DONE_FLAG.exists():
        _log(f"이미 완료됨 ({DONE_FLAG}) — 재실행 스킵")
        return

    total = _count_total()
    if total <= 0:
        _log(f"registry 없음 / 0 — 중단")
        return
    _log(f"대상 {total}개, polling {POLL_SEC}s 간격")

    # 1. 완료 대기
    last = -1
    while True:
        done = _count_done()
        if done != last:
            pct = 100.0 * done / max(total, 1)
            _log(f"caption progress: {done}/{total}  ({pct:.1f}%)")
            last = done
        if done >= total:
            _log("caption 완료 감지 → embed 단계 진입")
            break
        time.sleep(POLL_SEC)

    # 2. 임베딩 (L1/L2/L3)
    rc = _run(STEP_EMBED, "build_img_caption_triple.py --embed-only")
    if rc != 0:
        _log(f"embed 실패(rc={rc}) — recal 진행 안 함. 수동 점검 필요.")
        return

    # 3. calibration 재측정
    rc = _run(STEP_RECAL, "recalibrate_query_null.py")
    if rc != 0:
        _log(f"recal 실패(rc={rc}) — 수동 재실행 요망.")
        return

    DONE_FLAG.write_text(
        time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8",
    )
    _log(f"전 단계 완료. flag: {DONE_FLAG.name}")


if __name__ == "__main__":
    main()
