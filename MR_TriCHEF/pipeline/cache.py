"""npy/ids/segments 증분 append 헬퍼."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def append_npy(path: Path, new: np.ndarray) -> int:
    """기존 .npy 와 vstack 후 저장. 반환: 총 행 수."""
    if path.exists():
        prev = np.load(path)
        if prev.size == 0:
            merged = new
        elif prev.shape[1] != new.shape[1]:
            raise ValueError(f"dim mismatch: {prev.shape} vs {new.shape} @ {path.name}")
        else:
            merged = np.vstack([prev, new])
    else:
        merged = new
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, merged.astype(np.float32))
    return int(merged.shape[0])


def append_ids(path: Path, new_ids: list[str]) -> int:
    prev: list[str] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            prev = data.get("ids", [])
        except Exception:
            prev = []
    all_ids = prev + new_ids
    path.write_text(
        json.dumps({"ids": all_ids}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(all_ids)


def append_segments(path: Path, new_segs: list[dict]) -> int:
    prev: list[dict] = []
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(prev, list):
                prev = []
        except Exception:
            prev = []
    merged = prev + new_segs
    path.write_text(
        json.dumps(merged, ensure_ascii=False),
        encoding="utf-8",
    )
    return len(merged)


# ─── [P2B] replace-by-file 헬퍼 ──────────────────────────────────────────────
def _seg_fp(s: dict) -> str:
    return s.get("file_path") or s.get("file") or ""


def replace_by_file(
    cache_dir: Path,
    file_keys: list[str],
    arrays: dict[str, np.ndarray],
    new_ids: list[str],
    new_segs: list[dict] | None,
    npy_prefix: str,
    ids_file: str,
    segs_file: str | None = "segments.json",
) -> dict[str, int]:
    """[P2B.1] 동일 파일 재인덱싱 시 append 대신 기존 행을 제거하고 교체.

    기존 cache.append_* 는 항상 뒤에 붙이기 때문에, 파일 단위 재인덱싱
    (SHA mismatch) 시 ids/segments/npy 에 stale 엔트리가 누적된다. 본 함수는
    `file_keys` 에 포함된 파일들에 해당하는 행을 모든 npy + ids + segments
    에서 제거한 뒤 새 데이터를 append 하여 일관성을 유지한다.

    Args:
        cache_dir:   캐시 디렉토리 (MOVIE_CACHE_DIR 등)
        file_keys:   교체 대상 파일 relpath 목록 (ids 와 동일 포맷)
        arrays:      {"Re": ndarray, "Im": ndarray, ...} — 새 embedding.
                     키는 npy 파일 suffix (cache_{prefix}_{suffix}.npy).
        new_ids:     새로 추가될 ids (각 row 의 원본 파일 relpath).
        new_segs:    새로 추가될 segments (None → 생략).
        npy_prefix:  "cache_movie" or "cache_music"
        ids_file:    "movie_ids.json" 등
        segs_file:   "segments.json" (None 이면 segments 조작 skip)

    Returns:
        {"rows": 최종 행 수, "removed": 제거된 기존 행 수}
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    keyset = set(file_keys)

    # 1) 기존 ids 로드 → keep mask 계산
    ids_path = cache_dir / ids_file
    prev_ids: list[str] = []
    if ids_path.exists():
        try:
            data = json.loads(ids_path.read_text(encoding="utf-8"))
            prev_ids = data.get("ids", []) if isinstance(data, dict) else list(data)
        except Exception:
            prev_ids = []

    keep_mask = np.array([rid not in keyset for rid in prev_ids], dtype=bool)
    removed = int((~keep_mask).sum())

    # 2) 각 npy: keep_mask 로 slice → 새 arrays append
    final_rows = 0
    for suffix, new_arr in arrays.items():
        npy_path = cache_dir / f"{npy_prefix}_{suffix}.npy"
        if npy_path.exists() and len(prev_ids) > 0:
            prev = np.load(npy_path)
            if prev.shape[0] == len(prev_ids):
                kept = prev[keep_mask]
            else:
                # 길이 불일치 → 안전하게 전부 폐기보다는 원본 유지 후 경고
                import logging
                logging.getLogger("mr.cache").warning(
                    f"[replace_by_file] {npy_path.name} rows={prev.shape[0]} "
                    f"!= ids={len(prev_ids)} → keep_mask 적용 불가, prev 유지"
                )
                kept = prev
        else:
            kept = np.empty((0, new_arr.shape[1]), dtype=np.float32)

        if kept.size == 0:
            merged = new_arr
        elif new_arr.size == 0:
            merged = kept
        elif kept.shape[1] != new_arr.shape[1]:
            raise ValueError(
                f"dim mismatch: kept {kept.shape} vs new {new_arr.shape} @ {npy_path.name}"
            )
        else:
            merged = np.vstack([kept, new_arr])
        np.save(npy_path, merged.astype(np.float32))
        final_rows = int(merged.shape[0])

    # 3) ids 업데이트
    kept_ids = [rid for rid, k in zip(prev_ids, keep_mask) if k]
    all_ids = kept_ids + list(new_ids)
    ids_path.write_text(
        json.dumps({"ids": all_ids}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 4) segments (있을 때만)
    if segs_file is not None:
        seg_path = cache_dir / segs_file
        prev_segs: list[dict] = []
        if seg_path.exists():
            try:
                prev_segs = json.loads(seg_path.read_text(encoding="utf-8"))
                if not isinstance(prev_segs, list):
                    prev_segs = []
            except Exception:
                prev_segs = []
        kept_segs = [s for s in prev_segs if _seg_fp(s) not in keyset]
        merged_segs = kept_segs + list(new_segs or [])
        seg_path.write_text(
            json.dumps(merged_segs, ensure_ascii=False),
            encoding="utf-8",
        )

    return {"rows": final_rows, "removed": removed}
