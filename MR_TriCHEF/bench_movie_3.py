"""3 movie indexing pre-check -- measure real throughput.

실행:  python MR_TriCHEF/bench_movie_3.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# MR_TriCHEF 패키지 경로 주입
_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from pipeline.movie_runner import run_movie_incremental  # noqa: E402
from pipeline.paths import MOVIE_RAW_DIR, MOVIE_CACHE_DIR  # noqa: E402


def main(n_files: int = 3) -> int:
    print(f"[bench] source: {MOVIE_RAW_DIR}")
    print(f"[bench] cache:  {MOVIE_CACHE_DIR}")
    print(f"[bench] max {n_files} files then stop -- measurement run")

    t0 = time.time()
    results = []
    for res in run_movie_incremental(progress=lambda m: print(m, flush=True)):
        results.append(res)
        if len(results) >= n_files:
            print(f"\n[bench] {n_files} done -- stop")
            break
    elapsed = time.time() - t0

    done  = [r for r in results if r.status == "done"]
    skip  = [r for r in results if r.status == "skipped"]
    errs  = [r for r in results if r.status == "error"]

    print("\n" + "=" * 60)
    print(f"[bench] summary  elapsed={elapsed:.1f}s  "
          f"done={len(done)} skipped={len(skip)} errors={len(errs)}")
    for r in done:
        fps = (r.frames / r.duration) if r.duration else 0
        print(f"  DONE  {r.rel_path[:40]:40s} frames={r.frames} "
              f"dur={r.duration:.1f}s elapsed={r.elapsed}s "
              f"throughput={r.duration/r.elapsed:.2f}x RT")
    for r in errs:
        print(f"  ERR   {r.rel_path[:40]}: {r.reason}")

    if done:
        total_dur = sum(r.duration for r in done)
        total_el  = sum(r.elapsed  for r in done)
        est_full  = (total_el / total_dur) * (11.35 * 3600)
        print(f"\n[estimate] full 60 files ({11.35:.1f} hr of video) "
              f"ETA: {est_full/60:.1f} min ({est_full/3600:.2f} hr)")
    return 0


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    sys.exit(main(n))
