"""[P2B] App-side replace-by-file helper — 동일 파일 재인덱싱 시 stale 제거 후 교체.

MR_TriCHEF.pipeline.cache.replace_by_file 의 App 측 포팅본.
App 은 MR 패키지에 의존하지 않도록 독립 구현.

사용 위치:
- run_image_incremental / embed_image_file  (Img 도메인)
- run_doc_incremental  / embed_doc_file     (Doc 도메인)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("app.trichef.cache_ops")


def _fp(s: dict) -> str:
    return s.get("file_path") or s.get("file") or ""


def replace_by_file(
    cache_dir: Path,
    file_keys: list[str],
    arrays: dict[str, np.ndarray],   # {suffix_filename: ndarray}
    new_ids: list[str],
    ids_file: str,
    new_segs: list[dict] | None = None,
    segs_file: str | None = None,
) -> dict[str, int | np.ndarray]:
    """동일 file_keys 에 속한 기존 행 제거 후 새 행 append.

    Args:
        cache_dir:  캐시 디렉토리
        file_keys:  교체 대상 파일 relpath 목록 (ids 와 동일 키 포맷)
        arrays:     {"cache_img_Re_siglip2.npy": new_Re, ...} — 파일명 전체를 key 로.
        new_ids:    새로 추가될 row ids (len(new_ids) == new_arr.shape[0])
        ids_file:   "img_ids.json" 등
        new_segs:   선택. segments list (file_path 필드로 파일 매칭)
        segs_file:  선택. "segments.json" 등 — None 이면 segments 조작 skip.

    Returns:
        {
          "rows": 최종 행 수,
          "removed": 제거된 기존 행 수,
          "merged": {파일명: 최종 ndarray, ...}   # 후속 orthogonalize/upsert 용
        }
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    keyset = set(file_keys)

    # 1) 기존 ids 로드
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

    merged_out: dict[str, np.ndarray] = {}
    final_rows = 0
    for fname, new_arr in arrays.items():
        npy_path = cache_dir / fname
        if npy_path.exists() and len(prev_ids) > 0:
            prev = np.load(npy_path)
            if prev.shape[0] == len(prev_ids):
                kept = prev[keep_mask]
            elif prev.shape[0] > len(prev_ids):
                # 부분 쓰기(이전 실패)로 행이 초과됨 → prev_ids 기준으로 잘라낸 뒤 필터
                log.warning(
                    f"[replace_by_file] {fname} rows={prev.shape[0]} > ids={len(prev_ids)}"
                    f" → 초과 {prev.shape[0] - len(prev_ids)}행 잘라냄 (부분 쓰기 복구)"
                )
                kept = prev[:len(prev_ids)][keep_mask]
            else:
                # prev 행이 ids보다 적은 이상 상태 → 기존 데이터 전체 유지
                log.warning(
                    f"[replace_by_file] {fname} rows={prev.shape[0]} < ids={len(prev_ids)}"
                    f" → keep_mask 적용 불가, prev 전체 유지"
                )
                kept = prev
        else:
            kept = np.empty((0, new_arr.shape[1]), dtype=new_arr.dtype)

        if kept.size == 0:
            merged = new_arr
        elif new_arr.size == 0:
            merged = kept
        elif kept.shape[1] != new_arr.shape[1]:
            raise ValueError(
                f"dim mismatch: kept {kept.shape} vs new {new_arr.shape} @ {fname}"
            )
        else:
            merged = np.vstack([kept, new_arr])

        # PermissionError(WinError 32) 방지: 엔진이 메모리맵으로 물고 있을 경우
        # 임시 파일에 저장 후 교체
        import tempfile, shutil, os
        tmp_fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".npy")
        try:
            os.close(tmp_fd)
            np.save(tmp_path, merged)
            try:
                if npy_path.exists():
                    npy_path.unlink()
                shutil.move(tmp_path, npy_path)
            except PermissionError:
                # 파일이 잠긴 경우 덮어쓰기 재시도
                import time
                time.sleep(0.3)
                if npy_path.exists():
                    npy_path.unlink(missing_ok=True)
                shutil.move(tmp_path, npy_path)
        except Exception:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
            raise

        merged_out[fname] = merged
        final_rows = int(merged.shape[0])

    kept_ids = [rid for rid, k in zip(prev_ids, keep_mask) if k]
    all_ids = kept_ids + list(new_ids)
    ids_path.write_text(
        json.dumps({"ids": all_ids}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if segs_file is not None and new_segs is not None:
        seg_path = cache_dir / segs_file
        prev_segs: list[dict] = []
        if seg_path.exists():
            try:
                prev_segs = json.loads(seg_path.read_text(encoding="utf-8"))
                if not isinstance(prev_segs, list):
                    prev_segs = []
            except Exception:
                prev_segs = []
        kept_segs = [s for s in prev_segs if _fp(s) not in keyset]
        merged_segs = kept_segs + list(new_segs)
        seg_path.write_text(
            json.dumps(merged_segs, ensure_ascii=False),
            encoding="utf-8",
        )

    return {"rows": final_rows, "removed": removed, "merged": merged_out, "ids": all_ids}
