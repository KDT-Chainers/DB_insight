"""[P1] 동영상 빈 stt_text segment 정리.

배경:
  Data/embedded_DB/Movie/segments.json 46,797건 중 stt_text 가 빈 segment 가
  7,576건 (16.2%). 이들은 임베딩이 0벡터에 가까워 검색 노이즈만 발생시킨다.

동작:
  1) segments.json, movie_ids.json, cache_movie_{Re,Im,Z}.npy 4파일을 .pre_cleanup
     백업
  2) keep_mask = [stt_text 비어있지 않음] 생성
  3) 모든 4파일에 동일 mask 적용 → tmp 파일로 저장 후 원자적 이동
  4) sparse/vocab/token_sets 는 별도 rebuild 권장 (검색엔진 reload 시점에 자동 검증)

주의:
  - 실행 전 DB_insight 앱 종료 권장 (mmap 잠금 방지)
  - 백업 파일은 보존되므로 문제 시 .pre_cleanup → 원본 복원 가능
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

MV = Path(__file__).resolve().parents[3] / "Data" / "embedded_DB" / "Movie"


def _is_blank(seg: dict) -> bool:
    """stt_text / text / caption 모두 비어있으면 빈 segment."""
    for k in ("stt_text", "text", "caption"):
        v = (seg.get(k) or "").strip()
        if v:
            return False
    return True


def _atomic_replace(target: Path, new_bytes: bytes | None = None,
                    new_array: np.ndarray | None = None):
    """target 을 새 내용으로 교체 (mmap 잠금 회피용 tmp + move)."""
    tmp = target.with_suffix(target.suffix + f".tmp.{int(time.time())}")
    if new_bytes is not None:
        tmp.write_bytes(new_bytes)
    elif new_array is not None:
        np.save(tmp, new_array)
        # np.save 가 .npy 를 자동 추가하므로 보정
        if tmp.suffix != ".npy" and tmp.with_suffix(tmp.suffix + ".npy").exists():
            tmp.with_suffix(tmp.suffix + ".npy").rename(tmp)
    else:
        raise ValueError("new_bytes 또는 new_array 필요")
    try:
        if target.exists():
            target.unlink()
        shutil.move(tmp, target)
    except PermissionError:
        time.sleep(1.0)
        if target.exists():
            target.unlink(missing_ok=True)
        shutil.move(tmp, target)


def main():
    ts = int(time.time())
    print(f"=== 동영상 빈 segment 정리 (ts={ts}) ===")

    # 1) 로드
    seg_path = MV / "segments.json"
    ids_path = MV / "movie_ids.json"
    npy_paths = {
        "Re": MV / "cache_movie_Re.npy",
        "Im": MV / "cache_movie_Im.npy",
        "Z":  MV / "cache_movie_Z.npy",
    }

    segs = json.loads(seg_path.read_text(encoding="utf-8"))
    raw = json.loads(ids_path.read_text(encoding="utf-8"))
    ids = raw.get("ids", []) if isinstance(raw, dict) else list(raw)
    arrays = {k: np.load(p) for k, p in npy_paths.items()}

    # 2) 길이 정합 검증
    n0 = len(segs)
    if len(ids) != n0:
        print(f"[error] segments {n0} ≠ ids {len(ids)} — 정렬 깨짐, 중단")
        sys.exit(1)
    for k, arr in arrays.items():
        if arr.shape[0] != n0:
            print(f"[error] segments {n0} ≠ {k}.shape[0]={arr.shape[0]} — 중단")
            sys.exit(1)
    print(f"  4파일 정합 OK: {n0}건")

    # 3) 백업
    backup_suffix = f".pre_cleanup_{ts}"
    for p in [seg_path, ids_path, *npy_paths.values()]:
        bk = p.with_suffix(p.suffix + backup_suffix)
        shutil.copy2(p, bk)
        print(f"  백업: {p.name} → {bk.name}")

    # 4) keep_mask
    keep = np.array([not _is_blank(s) for s in segs], dtype=bool)
    n_keep = int(keep.sum())
    n_drop = n0 - n_keep
    print(f"  유지 {n_keep}건  /  제거 {n_drop}건 ({n_drop/n0*100:.1f}%)")
    if n_drop == 0:
        print("제거 대상 없음 — 종료")
        return

    # 5) 새 데이터
    new_segs = [s for s, k in zip(segs, keep) if k]
    new_ids = [i for i, k in zip(ids, keep) if k]
    new_arrays = {k: arr[keep] for k, arr in arrays.items()}

    # 6) 저장 (atomic)
    print("  저장 중 …")
    _atomic_replace(
        seg_path,
        new_bytes=json.dumps(new_segs, ensure_ascii=False).encode("utf-8"),
    )
    _atomic_replace(
        ids_path,
        new_bytes=json.dumps({"ids": new_ids}, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    for k, p in npy_paths.items():
        _atomic_replace(p, new_array=new_arrays[k])
        print(f"    ✓ {p.name}  shape={new_arrays[k].shape}")

    print(f"\n=== 완료 ===")
    print(f"  segments.json:    {n0} → {len(new_segs)}")
    print(f"  movie_ids.json:   {n0} → {len(new_ids)}")
    for k in npy_paths:
        print(f"  {npy_paths[k].name}: {n0} → {new_arrays[k].shape[0]}")
    print()
    print("후속 작업 권장:")
    print("  - 앱 재시작 (mmap 무효화)")
    print("  - 또는 검색 엔진 reload: routes.trichef.reload_engine()")
    print("  - rebuild_movie_lexical (sparse/vocab/token_sets 정합) — 별도 스크립트")
    print(f"\n백업 파일 (필요시 복원): *.pre_cleanup_{ts}")


if __name__ == "__main__":
    main()
