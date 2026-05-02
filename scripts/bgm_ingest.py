"""BGM 102 mp4 → 인덱스 빌드 CLI.

사용:
  python scripts/bgm_ingest.py                           # 증분 (이미 처리된 항목 skip)
  python scripts/bgm_ingest.py --rebuild                 # 전체 재빌드
  python scripts/bgm_ingest.py --src "<path>"            # src 지정
  python scripts/bgm_ingest.py --sync-acr                # ACR 메타 보강 (api_enabled=True 일 때만)

GPU: bgm_config.DEVICE 자동 (cuda 기본). FORCE_CPU=1 환경변수로 CPU fallback.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
APP_BACKEND = ROOT / "App" / "backend"
sys.path.insert(0, str(APP_BACKEND))


def _print_progress(stage: str, i: int, n: int, info: str) -> None:
    sys.stdout.write(f"\r[{stage}] {i}/{n}  {info[:60]:<60}")
    sys.stdout.flush()
    if i == n:
        sys.stdout.write("\n")
        sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default=None,
                        help="원본 mp4 폴더 (기본: raw_DB/Movie/정혜_BGM_1차)")
    parser.add_argument("--rebuild", action="store_true",
                        help="기존 캐시·인덱스 무시하고 전체 재빌드")
    parser.add_argument("--sync-acr", action="store_true",
                        help="ACR 메타 보강 (settings.bgm.api_enabled=True 필요)")
    parser.add_argument("--no-skip", action="store_true",
                        help="이미 처리된 항목도 강제 재처리")
    args = parser.parse_args()

    print("[bgm_ingest] 시작", flush=True)
    t0 = time.time()

    from services.bgm import ingest_pipeline

    summary = ingest_pipeline.build_index(
        src_dir=args.src,
        rebuild=args.rebuild,
        sync_acr=args.sync_acr,
        skip_existing=not args.no_skip,
        progress_cb=_print_progress,
    )

    elapsed = time.time() - t0
    print(f"\n[bgm_ingest] 완료 ({elapsed:.1f}s)", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if summary.get("ok", False) else 2


if __name__ == "__main__":
    sys.exit(main())
