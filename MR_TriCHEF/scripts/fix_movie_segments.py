"""Movie segments.json 정합성 복구.

⚠️  [DEPRECATED — 일회성 복구 스크립트] ⚠️
    P2B.1 (pipeline/cache.py::replace_by_file) 이후 이 mismatch 는 구조적으로
    재발하지 않음. 현재 segments.json 은 이미 재빌드되어 ids 와 일치 상태.
    **재실행 금지** — 멀쩡한 segments 를 "마지막 블록만 채택" 규칙으로 잘라내어
    오히려 손상시킬 수 있음. 이력 보존 목적으로만 남겨둠.

────────────────────────────────────────────────────────────────────────────
기존 문제 (이제 해결됨):
  증분 인덱싱/재인덱싱 과정에서 Re/ids 는 파일 단위 replace 되었지만
  segments.json 은 단순 append 되어 stale + duplicate 엔트리가 섞여 있음.
  (Re: 15703 rows, ids: 15703, segments: 16753 → 1050 초과)

복구 로직:
  1. 각 파일의 마지막 연속 블록(LAST contiguous block)이 현재 Re 에
     대응하는 세그먼트라고 가정 (재인덱싱 시 append 순서 보존).
  2. ids 순서대로 파일별 세그먼트 블록을 재조립하여 segments.json 재작성.
  3. 검증: len(rebuilt) == len(ids) 확인.

UTF-8 전용 출력 (Windows cp949 회피).
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parents[2]
D = _ROOT / "Data" / "embedded_DB" / "Movie"
SEG_PATH  = D / "segments.json"
IDS_PATH  = D / "movie_ids.json"
BACKUP    = D / "segments.json.bak_mismatch"


def _fp(s: dict) -> str:
    return s.get("file_path") or s.get("file") or ""


def _start(s: dict):
    v = s.get("start_sec", s.get("t_start"))
    return v if v is not None else -1.0


def main() -> None:
    segs = json.loads(SEG_PATH.read_text(encoding="utf-8"))
    ids_raw = json.loads(IDS_PATH.read_text(encoding="utf-8"))
    ids = ids_raw.get("ids", ids_raw) if isinstance(ids_raw, dict) else ids_raw

    print(f"[fix] before: segs={len(segs)}  ids={len(ids)}")

    # 1. 파일별 연속 블록 분할
    #    segments.json 은 파일 A의 모든 세그먼트가 연속 → 다음 파일 B 로 이어지는 구조.
    #    동일 파일이 두 번 등장하면 블록이 분리됨.
    blocks: dict[str, list[list[dict]]] = {}
    cur_fp: str | None = None
    cur_block: list[dict] = []

    def flush() -> None:
        nonlocal cur_fp, cur_block
        if cur_fp is not None and cur_block:
            blocks.setdefault(cur_fp, []).append(cur_block)
        cur_fp = None
        cur_block = []

    for s in segs:
        fp = _fp(s)
        if fp != cur_fp:
            flush()
            cur_fp = fp
            cur_block = [s]
        else:
            cur_block.append(s)
    flush()

    dup_files = [fp for fp, bs in blocks.items() if len(bs) > 1]
    print(f"[fix] 블록 split: {sum(len(bs) for bs in blocks.values())}개 블록, "
          f"중복 파일 {len(dup_files)}개")
    for fp in dup_files:
        bs = blocks[fp]
        print(f"   - {fp[-40:]:>40s}  blocks={len(bs)}  sizes={[len(b) for b in bs]}")

    # 2. 각 파일: 마지막 블록만 채택 (최신 재인덱싱 결과)
    latest_for: dict[str, list[dict]] = {
        fp: bs[-1] for fp, bs in blocks.items()
    }

    # 3. ids 순서대로 재조립
    rebuilt: list[dict] = []
    missing: list[str] = []
    for rel in _unique_in_order(ids):
        if rel in latest_for:
            rebuilt.extend(latest_for[rel])
        else:
            missing.append(rel)

    if missing:
        print(f"[fix] WARNING: ids 에 있으나 segments 에 없는 파일 {len(missing)}개")
        for m in missing[:5]:
            print(f"   - {m}")

    if len(rebuilt) != len(ids):
        print(f"[fix] MISMATCH: rebuilt={len(rebuilt)}  ids={len(ids)}")
        print("      → 백업은 만들었지만 덮어쓰지 않음. 수동 점검 필요.")
        SEG_PATH.with_suffix(".json.rebuilt_trial").write_text(
            json.dumps(rebuilt, ensure_ascii=False), encoding="utf-8",
        )
        return

    # 4. 백업 후 쓰기
    if not BACKUP.exists():
        BACKUP.write_bytes(SEG_PATH.read_bytes())
        print(f"[fix] backup: {BACKUP.name}")
    SEG_PATH.write_text(json.dumps(rebuilt, ensure_ascii=False), encoding="utf-8")
    print(f"[fix] after:  segs={len(rebuilt)} (matches ids)")


def _unique_in_order(xs: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


if __name__ == "__main__":
    import os
    if os.environ.get("FIX_MOVIE_SEGMENTS_FORCE") != "1":
        print("[fix_movie_segments] DEPRECATED — P2B.1 이후 재실행 금지.")
        print("  재실행이 정말 필요하면: "
              "set FIX_MOVIE_SEGMENTS_FORCE=1 && python fix_movie_segments.py")
        raise SystemExit(2)
    main()
