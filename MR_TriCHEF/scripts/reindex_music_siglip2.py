"""reindex_music_siglip2.py — Music Re 축 SigLIP2 전환 후 전체 재인덱싱.

기존 cache_music_Re.npy(BGE-M3 1024d) → SigLIP2 text-encoder(1152d) 로 교체.
변경 사항:
  Re: BGE-M3 1024d → SigLIP2 text 1152d  (Movie Re와 동일 공간, 크로스-도메인 호환)
  Im: BGE-M3 1024d (유지)
  Z:  zeros 1024d  (유지)

실행:
    python MR_TriCHEF/scripts/reindex_music_siglip2.py
    python MR_TriCHEF/scripts/reindex_music_siglip2.py --dry-run
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "MR_TriCHEF"))

from pipeline.paths import MUSIC_CACHE_DIR


def backup_and_clear(dry_run: bool = False):
    """기존 캐시 백업 후 삭제 → 재인덱싱 준비."""
    bak = MUSIC_CACHE_DIR.parent / "Rec_backup_siglip2"

    targets = [
        MUSIC_CACHE_DIR / "cache_music_Re.npy",
        MUSIC_CACHE_DIR / "cache_music_Im.npy",
        MUSIC_CACHE_DIR / "cache_music_Z.npy",
        MUSIC_CACHE_DIR / "music_ids.json",
        MUSIC_CACHE_DIR / "segments.json",
        MUSIC_CACHE_DIR / "registry.json",
    ]
    existing = [p for p in targets if p.exists()]

    if dry_run:
        print("[dry-run] 백업 대상:")
        for p in existing:
            print(f"  {p.name}")
        print(f"  → {bak}/")
        return

    if existing:
        bak.mkdir(parents=True, exist_ok=True)
        for p in existing:
            shutil.copy2(p, bak / p.name)
            p.unlink()
            print(f"  백업 후 삭제: {p.name}")
        print(f"  백업 저장: {bak}")
    else:
        print("  기존 캐시 없음 — 백업 불필요")


def run_reindex(dry_run: bool = False):
    """music_runner.run_music_incremental 실행."""
    if dry_run:
        print("[dry-run] music 재인덱싱 실행 생략")
        return

    from pipeline.music_runner import run_music_incremental

    print("\n[reindex] Music 재인덱싱 시작 (SigLIP2 Re + BGE-M3 Im)")
    print("  ※ SigLIP2(~3GB) + BGE-M3(~3GB) 순차 로드 — VRAM 8GB 안전")
    print()

    results = list(run_music_incremental(progress=print))

    done  = sum(1 for r in results if r.status == "done")
    skip  = sum(1 for r in results if r.status == "skipped")
    error = sum(1 for r in results if r.status == "error")
    print(f"\n[reindex] 완료: done={done}  skip={skip}  error={error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="실제 실행 없이 계획만 출력")
    args = parser.parse_args()

    print("=" * 60)
    print("Music Re 축 SigLIP2 전환 재인덱싱")
    print(f"캐시 경로: {MUSIC_CACHE_DIR}")
    print("=" * 60)

    print("\n[Step 1] 기존 캐시 백업 및 삭제")
    backup_and_clear(dry_run=args.dry_run)

    print("\n[Step 2] 전체 재인덱싱")
    run_reindex(dry_run=args.dry_run)

    if not args.dry_run:
        print("\n[완료] music 캐시가 SigLIP2 Re(1152d)로 교체되었습니다.")
        print("  다음 단계:")
        print("  1. python MR_TriCHEF/pipeline/calibration.py (Music calibration 재측정)")
        print("  2. App/backend 서버 재시작 → music 검색 확인")


if __name__ == "__main__":
    sys.exit(main())
