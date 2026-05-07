"""CLI 인덱싱 러너 — Gradio 없이 직접 실행."""
from __future__ import annotations

import io
import sys
import time

# Windows cp949 터미널에서 이모지/한글 깨짐 방지
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

if __name__ == "__main__":
    scope = sys.argv[1] if len(sys.argv) > 1 else "all"
    t0 = time.time()

    def log(m: str):
        print(m, flush=True)

    if scope in ("movie", "all"):
        from pipeline.movie_runner import run_movie_incremental
        log("=" * 60)
        log("MOVIE INDEXING")
        log("=" * 60)
        for res in run_movie_incremental(progress=log):
            log(f"  >> {res}")

    if scope in ("music", "all"):
        from pipeline.music_runner import run_music_incremental
        log("=" * 60)
        log("MUSIC INDEXING")
        log("=" * 60)
        for res in run_music_incremental(progress=log):
            log(f"  >> {res}")

    log(f"\n[total elapsed] {time.time() - t0:.1f}s")
