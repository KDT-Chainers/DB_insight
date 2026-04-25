"""MR_TriCHEF/scripts/run_movie_incremental.py — Movie 파일 1개씩 증분 인덱싱.

기존 `incremental_index_and_bench.py` 의 `index_one_file` 로직을 재사용.
per-file calibration/bench 는 제거 (시간 절약). 인덱싱 완료 후 별도로
`run_calibration.py` 를 돌릴 것.

사용:
    python MR_TriCHEF/scripts/run_movie_incremental.py
        --target-dir Data/raw_DB/Movie/YS_다큐_1차
        [--max 1]       # 1개만 처리 후 종료 (스모크)
        [--dry-run]     # 처리 없이 pending 목록만 출력

행동:
  - target-dir 하위에서 MOVIE_EXTS 파일을 재귀 스캔
  - registry.json 에 없는 rel_path 만 pending
  - pending 에 대해 한 파일씩 `index_one_file` 호출
  - 각 파일 완료 직후 registry/cache 저장 (SHA 기반 재시작 안전)
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "MR_TriCHEF"))

from pipeline import registry as reg_mod  # noqa: E402
from pipeline.paths import MOVIE_CACHE_DIR, MOVIE_EXTS, MOVIE_RAW_DIR  # noqa: E402

# index_one_file 은 검증된 logic → 그대로 재사용
from scripts.incremental_index_and_bench import index_one_file  # noqa: E402


def _rel(p: Path) -> str:
    return str(p.relative_to(MOVIE_RAW_DIR)).replace("\\", "/")


def pending_in(target: Path) -> list[Path]:
    reg = reg_mod.load(MOVIE_CACHE_DIR / "registry.json")
    done = set(reg.keys())
    out: list[Path] = []
    for p in sorted(target.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in MOVIE_EXTS:
            continue
        if _rel(p) in done:
            continue
        out.append(p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-dir", type=str,
                    default="Data/raw_DB/Movie/YS_다큐_1차")
    ap.add_argument("--max", type=int, default=0,
                    help="처리할 최대 파일 수 (0 = 전체)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    target = Path(args.target_dir)
    if not target.is_absolute():
        target = _ROOT / args.target_dir
    if not target.exists():
        print(f"[err] target 폴더 없음: {target}")
        sys.exit(2)

    pending = pending_in(target)
    print(f"[scan] {target.relative_to(_ROOT)}")
    print(f"[scan] pending = {len(pending)}")
    for p in pending[:5]:
        print(f"   - {_rel(p)}")
    if len(pending) > 5:
        print(f"   ... (+{len(pending)-5})")

    if args.dry_run:
        print("[dry-run] 종료")
        return

    limit = args.max if args.max > 0 else len(pending)
    todo = pending[:limit]
    print(f"\n[run] 처리 대상 {len(todo)} / pending {len(pending)}")

    t_all = time.time()
    ok = err = skip = 0
    for i, vid in enumerate(todo, 1):
        rel = _rel(vid)
        size_mb = vid.stat().st_size / (1024 * 1024)
        print(f"\n[{i}/{len(todo)}] {rel}  ({size_mb:.1f} MB)")
        r = index_one_file(vid)
        st = r.get("status", "?")
        if st == "done":
            ok += 1
            print(f"   ✓ done  frames={r.get('frames',0)}  "
                  f"dur={r.get('duration',0):.1f}s  el={r.get('elapsed',0)}s")
        elif st == "skipped":
            skip += 1
            print(f"   — skipped ({r.get('reason','?')})")
        else:
            err += 1
            print(f"   ✗ error: {r.get('reason','?')}")

    el_all = time.time() - t_all
    print("\n" + "=" * 60)
    print(f"[summary] done={ok}  skipped={skip}  error={err}")
    print(f"[summary] 총 소요: {el_all/60:.1f}분 ({el_all:.0f}s)")
    if ok:
        print(f"[summary] 파일당 평균: {el_all/ok/60:.1f}분")


if __name__ == "__main__":
    main()
