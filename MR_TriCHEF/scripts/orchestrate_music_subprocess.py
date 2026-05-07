"""orchestrate_music_subprocess.py — 음원별 subprocess 격리 재인덱싱.

파일 7번에서 Python 프로세스 레벨 크래시(exit 9) 발생 → subprocess 격리로 해결.
각 파일을 별도 Python 프로세스에서 처리. 한 파일이 크래시해도 다음 파일은 계속.

실행:
    python MR_TriCHEF/scripts/orchestrate_music_subprocess.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "MR_TriCHEF"))

from pipeline.paths import MUSIC_RAW_DIR, MUSIC_CACHE_DIR
from pipeline.music_runner import iter_music_files


def main():
    files = iter_music_files()
    reg_path = MUSIC_CACHE_DIR / "registry.json"

    print("[orchestrate] 음원 " + str(len(files)) + "개 대상")
    print("[orchestrate] 각 파일 subprocess 격리 실행\n")

    results: list[tuple[str, str]] = []
    for idx, aud in enumerate(files, 1):
        rel = str(aud.relative_to(MUSIC_RAW_DIR)).replace("\\", "/")
        print("=" * 60)
        print("[" + str(idx) + "/" + str(len(files)) + "] " + rel)
        print("=" * 60)

        # registry 선확인: 이미 sha 일치면 subprocess 없이 즉시 skip
        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.exists() else {}
        except Exception:
            reg = {}
        if rel in reg and reg[rel].get("windows", 0) > 0:
            print("  (registry 등록됨 — subprocess 생략)")
            results.append((rel, "pre-registered"))
            continue

        t0 = time.time()
        cmd = [sys.executable, "-u",
               str(Path(__file__).parent / "process_one_music.py"),
               rel]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        try:
            ret = subprocess.run(cmd, cwd=str(_root), env=env,
                                 timeout=1800)
            rc = ret.returncode
        except subprocess.TimeoutExpired:
            rc = -1
        el = round(time.time() - t0, 1)
        status = "ok" if rc == 0 else ("crash(" + str(rc) + ")")
        print("  [" + status + "] elapsed=" + str(el) + "s\n")
        results.append((rel, status))

    print("\n" + "=" * 60)
    print("전체 결과:")
    for rel, st in results:
        print("  [" + st + "] " + rel)
    print("=" * 60)

    ok = sum(1 for _, s in results if s in ("ok", "pre-registered"))
    fail = len(results) - ok
    print("\n성공: " + str(ok) + "  실패: " + str(fail))


if __name__ == "__main__":
    sys.exit(main())
