"""BGM 세그먼트 단위 인덱싱 — 30s 윈도우, 10s hop.

기존 file-level 인덱스 (cache_clap.npy) 와 별도로 추가 운영.
출력: cache_seg_emb.npy + cache_seg_index.json + cache_seg_faiss.faiss

사용:
  FORCE_CPU=1 python scripts/bgm_segment_ingest.py
  python scripts/bgm_segment_ingest.py --window 30 --hop 10
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=float, default=30.0,
                        help="세그먼트 윈도우 길이 (초, 기본 30)")
    parser.add_argument("--hop", type=float, default=10.0,
                        help="세그먼트 hop (초, 기본 10 — overlap 20s)")
    parser.add_argument("--force", action="store_true",
                        help="기존 segment 인덱스 무시하고 재계산")
    args = parser.parse_args()

    print(f"[bgm_segment_ingest] window={args.window}s hop={args.hop}s", flush=True)
    t0 = time.time()

    from services.bgm.segments import build_segment_index

    summary = build_segment_index(
        window=args.window,
        hop=args.hop,
        skip_existing_seg=not args.force,
        progress_cb=_print_progress,
    )
    elapsed = time.time() - t0
    print(f"\n[bgm_segment_ingest] 완료 ({elapsed:.0f}s)", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if summary.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
