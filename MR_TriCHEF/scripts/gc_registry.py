"""gc_registry.py -- Registry orphan cleanup.

Usage:
    python MR_TriCHEF/scripts/gc_registry.py            # dry-run (report only)
    python MR_TriCHEF/scripts/gc_registry.py --apply    # actually remove orphans
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "MR_TriCHEF"))

from pipeline.paths import (
    MOVIE_RAW_DIR, MOVIE_CACHE_DIR,
    MUSIC_RAW_DIR, MUSIC_CACHE_DIR,
    MOVIE_EXTS, MUSIC_EXTS,
)


def gc_domain(
    raw_dir: Path,
    cache_dir: Path,
    exts: set[str],
    domain: str,
    apply: bool,
) -> int:
    """Registry 에서 raw_dir 에 존재하지 않는 항목을 찾아 보고(또는 삭제).

    Returns: number of orphans found.
    """
    reg_path = cache_dir / "registry.json"
    if not reg_path.exists():
        print(f"[{domain}] registry 없음 — 건너뜀")
        return 0

    reg: dict = json.loads(reg_path.read_text(encoding="utf-8"))
    existing: set[str] = {
        str(p.relative_to(raw_dir)).replace("\\", "/")
        for p in raw_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in exts
    } if raw_dir.exists() else set()

    orphans = [k for k in reg if k not in existing]
    print(f"\n[{domain}] registry={len(reg)}  on-disk={len(existing)}  orphans={len(orphans)}")

    for k in orphans:
        flag = "REMOVE" if apply else "ORPHAN"
        print(f"  {flag}: {k}")

    if apply and orphans:
        for k in orphans:
            del reg[k]
        reg_path.write_text(
            json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  -> {len(orphans)}개 항목 제거 완료")

    return len(orphans)


def main(apply: bool = False) -> int:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"=== Registry GC ({mode}) ===")

    total = 0
    total += gc_domain(MOVIE_RAW_DIR, MOVIE_CACHE_DIR, MOVIE_EXTS, "movie", apply)
    total += gc_domain(MUSIC_RAW_DIR, MUSIC_CACHE_DIR, MUSIC_EXTS, "music", apply)

    print(f"\n합계: orphan {total}개 {'제거됨' if apply else '(dry-run, --apply 로 실제 삭제)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
