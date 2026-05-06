"""모든 도메인 registry.json + BGM audio_meta.json 의 PC 별 abs 경로 정리.

수행 작업:
  1. embedded_DB/{Doc,Img,Movie,Rec}/registry.json
       - 각 entry 의 'abs' 필드 제거
       - 각 entry 의 'abs_aliases' 필드 제거
       - rel_key (registry key) 만 유지하면 다른 PC 에서 resolve_raw_path 로 결합 가능
  2. embedded_DB/Bgm/audio_meta.json
       - 각 item 의 'path' 필드 제거 (filename + RAW_BGM_DIR 동적 결합)

실행 1회 → git commit → 다른 PC 들 git pull 시 자동 호환.
원본은 .bak 로 백업.

사용:
    python scripts/normalize_registry_paths.py            # 실제 적용
    python scripts/normalize_registry_paths.py --dry-run  # 변경 미리보기
"""
from __future__ import annotations
import sys, os, json, shutil, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import EMBEDDED_DB  # type: ignore


def normalize_registry(registry_path: Path, *, dry_run: bool) -> tuple[int, int]:
    """registry.json 한 개 처리. (entries 처리, abs 제거 수) 반환."""
    if not registry_path.exists():
        return 0, 0
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return 0, 0

    removed = 0
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        if "abs" in entry:
            entry.pop("abs")
            removed += 1
        if "abs_aliases" in entry:
            entry.pop("abs_aliases")
            removed += 1

    if not dry_run and removed > 0:
        backup = registry_path.with_suffix(registry_path.suffix + ".bak")
        if not backup.exists():
            shutil.copy(registry_path, backup)
        registry_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return len(data), removed


def normalize_audio_meta(meta_path: Path, *, dry_run: bool) -> tuple[int, int]:
    """BGM audio_meta.json 처리. 'path' 필드 제거."""
    if not meta_path.exists():
        return 0, 0
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else (
        list(data.values()) if isinstance(data, dict) else []
    )
    removed = 0
    for it in items:
        if isinstance(it, dict) and "path" in it:
            it.pop("path")
            removed += 1

    if not dry_run and removed > 0:
        backup = meta_path.with_suffix(meta_path.suffix + ".bak")
        if not backup.exists():
            shutil.copy(meta_path, backup)
        meta_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return len(items), removed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="변경 사항 미리보기만 (파일 쓰지 않음)")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    print(f"[normalize] EMBEDDED_DB = {EMBEDDED_DB}")
    print(f"[normalize] dry_run     = {args.dry_run}")
    print()

    total_entries = 0
    total_removed = 0

    # registry.json (Doc/Img/Movie/Rec)
    for dom in ("Doc", "Img", "Movie", "Rec"):
        p = EMBEDDED_DB / dom / "registry.json"
        n, r = normalize_registry(p, dry_run=args.dry_run)
        total_entries += n
        total_removed += r
        print(f"  [{dom:5}] entries={n:5}  abs/aliases 제거={r}")

    # audio_meta.json (BGM)
    bp = EMBEDDED_DB / "Bgm" / "audio_meta.json"
    n, r = normalize_audio_meta(bp, dry_run=args.dry_run)
    total_entries += n
    total_removed += r
    print(f"  [BGM  ] items={n:5}  path 제거={r}")

    print()
    print(f"총 entries: {total_entries}, 제거된 abs 필드: {total_removed}")
    if args.dry_run:
        print("(dry-run — 파일 미변경)")
    else:
        print("(.bak 백업 생성 + 원본 갱신)")


if __name__ == "__main__":
    main()
