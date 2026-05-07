"""index_bgm_1cha.py — 정혜_BGM_1차 동영상 증분 인덱싱.

정혜_BGM_1차/ 폴더의 102개 mp4 를 Movie 도메인으로 인덱싱.
BGM(배경음악) 영상이므로 Whisper STT 텍스트가 적거나 없을 수 있음.
SigLIP2 프레임 임베딩(Re) 은 정상 생성됨.

실행:
    python MR_TriCHEF/scripts/index_bgm_1cha.py --dry-run
    python MR_TriCHEF/scripts/index_bgm_1cha.py
    python MR_TriCHEF/scripts/index_bgm_1cha.py --max 10   # 10개씩 배치
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "MR_TriCHEF"))

from pipeline.paths import MOVIE_CACHE_DIR, MOVIE_RAW_DIR, MOVIE_EXTS

BGM_DIR = MOVIE_RAW_DIR / "정혜_BGM_1차"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=0,
                        help="최대 처리 파일 수 (0=전체)")
    parser.add_argument("--dry-run", action="store_true",
                        help="인덱싱 없이 대상 목록만 출력")
    args = parser.parse_args()

    if not BGM_DIR.exists():
        print(f"[오류] {BGM_DIR} 없음")
        return 1

    # 전체 BGM 파일 목록
    all_files = sorted(p for p in BGM_DIR.rglob("*")
                       if p.is_file() and p.suffix.lower() in MOVIE_EXTS)
    print(f"[bgm_1차] 정혜_BGM_1차 파일: {len(all_files)}개")

    # 레지스트리에서 이미 인덱싱된 파일 확인
    reg_path = MOVIE_CACHE_DIR / "registry.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.exists() else {}
    pending = []
    for p in all_files:
        rel = str(p.relative_to(MOVIE_RAW_DIR)).replace("\\", "/")
        if rel not in reg:
            pending.append(p)
        else:
            pass  # 이미 인덱싱됨

    print(f"  이미 완료: {len(all_files)-len(pending)}개")
    print(f"  대기 중:   {len(pending)}개")

    if args.dry_run:
        print(f"\n[dry-run] 처리 예정 파일 (최대 {args.max if args.max else '전체'}):")
        show = pending[:args.max] if args.max else pending
        for p in show[:20]:
            print(f"  {p.name[:70]}")
        if len(show) > 20:
            print(f"  ... 외 {len(show)-20}개")
        return 0

    if not pending:
        print("  모두 인덱싱됨.")
        return 0

    target = pending[:args.max] if args.max else pending
    print(f"\n[bgm_1차] {len(target)}개 인덱싱 시작 (stage-sequential VRAM)")

    from scripts.incremental_index_and_bench import index_one_file

    done_cnt = skip_cnt = error_cnt = 0
    t_total = time.time()

    for i, mp4 in enumerate(target, 1):
        rel = str(mp4.relative_to(MOVIE_RAW_DIR)).replace("\\", "/")
        print(f"\n[{i}/{len(target)}] {mp4.name[:70]}")
        t0 = time.time()
        result = index_one_file(mp4)
        elapsed = round(time.time() - t0, 1)

        status = result.get("status", "error")
        if status == "done":
            done_cnt += 1
            print(f"  완료: frames={result.get('frames')} "
                  f"duration={result.get('duration',0):.0f}s elapsed={elapsed}s")
        elif status == "skipped":
            skip_cnt += 1
            print(f"  스킵: {result.get('reason','')}")
        else:
            error_cnt += 1
            print(f"  오류: {result.get('reason','')[:200]}")

    total_elapsed = round(time.time() - t_total, 1)
    print(f"\n[bgm_1차] 완료: done={done_cnt} skip={skip_cnt} error={error_cnt} "
          f"/ 총 {total_elapsed}s ({total_elapsed/60:.1f}분)")

    # 현재 캐시 상태 요약
    Re = np.load(MOVIE_CACHE_DIR / "cache_movie_Re.npy")
    ids_raw = json.loads((MOVIE_CACHE_DIR / "movie_ids.json").read_text("utf-8"))
    ids = ids_raw if isinstance(ids_raw, list) else ids_raw.get("ids", [])
    unique_files = len(set(ids))
    print(f"\n[캐시 현황] Re: {Re.shape} / 파일: {unique_files}개 / 세그먼트: {len(ids)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
