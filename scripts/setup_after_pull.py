"""다른 PC 에서 git pull 받은 후 한 번 실행 — 경로 자동 정규화.

수행 작업:
  1. 현재 PC 의 repo root 자동 감지 (스크립트 위치 기준)
  2. raw_DB 디렉터리 존재 확인 (없으면 안내)
  3. 5개 도메인 (Doc/Img/Movie/Rec/Bgm) registry/meta 의 abs 경로 갱신
  4. 디스크 미존재 파일 카운트 보고

사용:
  python scripts/setup_after_pull.py             # 정규화 적용
  python scripts/setup_after_pull.py --dry-run   # 변경 없이 보고만

이후:
  python App/backend/app.py
  → http://localhost:5001 (Flask 백엔드)
  → 별도 터미널: cd App/frontend && npm run dev (또는 빌드된 .exe)
"""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
RAW_DB = ROOT / "Data" / "raw_DB"
EMB_DB = ROOT / "Data" / "embedded_DB"


def banner():
    print("=" * 65, flush=True)
    print(f"  DB_insight 새 PC 설정", flush=True)
    print("=" * 65, flush=True)
    print(f"  ROOT:    {ROOT}", flush=True)
    print(f"  RAW_DB:  {RAW_DB}", flush=True)
    print(f"  EMB_DB:  {EMB_DB}", flush=True)
    print()


def check_directories() -> bool:
    print("[1/3] 디렉터리 존재 확인", flush=True)
    issues = []
    if not (ROOT / "App" / "backend").is_dir():
        issues.append(f"  App/backend 미존재 — git pull 완료 후 실행하세요")
    if not RAW_DB.is_dir():
        issues.append(f"  Data/raw_DB 미존재 — Releases 의 raw_DB.zip 을 압축 해제하세요")
    if not EMB_DB.is_dir():
        issues.append(f"  Data/embedded_DB 미존재 — Releases 의 embedded_DB.zip 을 압축 해제하세요")

    if issues:
        print("\n  ❌ 문제 발견:", flush=True)
        for i in issues:
            print(i, flush=True)
        return False
    print("  ✓ App/backend, Data/raw_DB, Data/embedded_DB 존재", flush=True)
    return True


def list_raw_subdirs():
    print(f"\n[2/3] raw_DB 하위 디렉터리", flush=True)
    if not RAW_DB.is_dir():
        return
    for p in sorted(RAW_DB.iterdir()):
        if p.is_dir():
            n = sum(1 for _ in p.rglob("*") if _.is_file())
            print(f"  {p.name}/ ({n} files)", flush=True)


def normalize(dry_run: bool) -> int:
    print(f"\n[3/3] 경로 정규화 ({'dry-run' if dry_run else 'apply'})", flush=True)
    cmd = [sys.executable, str(ROOT / "scripts" / "normalize_registry_paths.py")]
    if dry_run:
        cmd.append("--dry-run")
    return subprocess.run(cmd, check=False).returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="실제 변경 없이 어떤 작업이 일어날지만 보고")
    args = parser.parse_args()

    banner()

    if not check_directories():
        print("\n위 문제를 해결한 후 다시 실행하세요.", flush=True)
        return 2

    list_raw_subdirs()

    rc = normalize(args.dry_run)
    if rc != 0:
        print(f"\n❌ 경로 정규화 실패 (rc={rc})", flush=True)
        return rc

    print()
    print("=" * 65, flush=True)
    print("  ✓ 설정 완료", flush=True)
    print("=" * 65, flush=True)
    print("  다음 단계:", flush=True)
    print(f"    1. cd App/backend && python app.py", flush=True)
    print(f"    2. (배포 .exe) App/frontend/out/DB_insight 0.1.0.exe 실행", flush=True)
    print(f"       또는 (개발) cd App/frontend && npm run electron:dev", flush=True)
    print(flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
