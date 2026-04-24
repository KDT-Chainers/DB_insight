"""fix_1cha_registry.py — 훤_youtube_1차 레지스트리 경로 수정 후 재인덱싱.

문제:
  기존 레지스트리에 1차 파일들이 파일명만으로 등록됨 (예: "파일명.mp4")
  현재 MOVIE_RAW_DIR = RAW_ROOT/Movie 이므로 올바른 키는 "훤_youtube_1차/파일명.mp4"
  → SHA 매칭으로 skip → numpy cache 에 데이터 없음 → 검색 불가

수정:
  1. 잘못된 registry 키 제거 (파일명만인 5개)
  2. 해당 numpy rows 도 없으므로 추가 조치 불필요
  3. movie_runner 로 1차 파일 재인덱싱 (올바른 경로 키로 등록됨)

실행:
    python MR_TriCHEF/scripts/fix_1cha_registry.py --dry-run
    python MR_TriCHEF/scripts/fix_1cha_registry.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "MR_TriCHEF"))

from pipeline.paths import MOVIE_CACHE_DIR, MOVIE_RAW_DIR


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    reg_path = MOVIE_CACHE_DIR / "registry.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8"))

    # 올바른 경로 키: "훤_youtube_1차/파일명.mp4" 또는 "훤_youtube_2차/..."
    # 잘못된 키: 슬래시 없이 파일명만
    bad_keys = [k for k in reg if "/" not in k and "\\" not in k]
    print(f"[fix_1cha] 레지스트리 총 {len(reg)}개")
    print(f"  잘못된 키(경로 없음): {len(bad_keys)}개")
    for k in bad_keys:
        print(f"    제거 예정: {k[:80]}")

    if not bad_keys:
        print("  수정 불필요.")
        return

    if args.dry_run:
        print("\n[dry-run] 실제 변경 없음. --dry-run 제거 후 재실행하세요.")
        return

    # 잘못된 키 제거
    for k in bad_keys:
        del reg[k]
    reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  레지스트리 저장 완료 ({len(reg)}개 남음)")

    # 훤_youtube_1차 만 재인덱싱 (정혜_BGM_1차 102개 는 별도 결정)
    target_dir = MOVIE_RAW_DIR / "훤_youtube_1차"
    if not target_dir.exists():
        print(f"\n[fix_1cha] 오류: {target_dir} 없음")
        return

    from pipeline.paths import MOVIE_EXTS
    target_files = sorted(p for p in target_dir.rglob("*")
                          if p.is_file() and p.suffix.lower() in MOVIE_EXTS)
    print(f"\n[fix_1cha] 훤_youtube_1차 재인덱싱: {len(target_files)}개 파일")

    # incremental_index_and_bench.index_one_file 재사용 (stage-sequential VRAM 안전)
    from scripts.incremental_index_and_bench import index_one_file
    done_cnt = 0
    for mp4 in target_files:
        rel = str(mp4.relative_to(MOVIE_RAW_DIR)).replace("\\", "/")
        print(f"\n  처리: {rel}")
        result = index_one_file(mp4)
        if result.get("status") == "done":
            done_cnt += 1
            print(f"  완료: frames={result.get('frames')} elapsed={result.get('elapsed')}s")
        elif result.get("status") == "skipped":
            print(f"  스킵: {result.get('reason','')}")
        else:
            print(f"  오류: {result.get('reason','')}")

    print(f"\n[fix_1cha] 완료: {done_cnt}/{len(target_files)}개 재인덱싱")
    print("  훤_youtube_1차 파일이 올바른 경로 키(훤_youtube_1차/파일명)로 등록됨")


if __name__ == "__main__":
    sys.exit(main())
