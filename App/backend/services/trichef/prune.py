"""services/trichef/prune.py — 삭제된 파일 정합성 동기화 (v2 P1).

incremental_runner 의 run_*_incremental 최상단에 호출.
registry·.npy·ids.json·ChromaDB 에서 stale 엔트리 일괄 제거.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import chromadb
import numpy as np
from chromadb.config import Settings
from scipy import sparse as sp

from config import PATHS

logger = logging.getLogger(__name__)


def _load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_json(p: Path, data) -> None:
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_col(name: str):
    client = chromadb.PersistentClient(
        path=str(Path(PATHS["TRICHEF_CHROMA"])),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})


def prune_domain(
    domain: str,
    raw_dir: Path,
    cache_dir: Path,
    registry: dict,
    current_keys: set[str],
    npy_bases: list[str],
    ids_filename: str,
    col_name: str,
    captions_dir: Path | None = None,
    hard: bool = False,
) -> tuple[dict, int]:
    """
    Returns: (registry 갱신됨, stale 제거 개수)
    npy_bases: 예) ["cache_img_Re_siglip2", "cache_img_Im_e5cap", "cache_img_Z_dinov2"]
    """
    stale = set(registry.keys()) - current_keys
    if not stale:
        return registry, 0

    ids_path = cache_dir / ids_filename
    ids_data = _load_json(ids_path)
    ids: list[str] = ids_data.get("ids", [])

    if ids:
        keep_mask = np.array([i not in stale for i in ids], dtype=bool)

        # .npy 각 축 row 필터링
        for base in npy_bases:
            p = cache_dir / f"{base}.npy"
            if not p.exists():
                continue
            arr = np.load(p)
            if arr.shape[0] != len(ids):
                logger.warning(f"[prune] {p.name} 행 수 불일치 → 건너뜀")
                continue
            np.save(p, arr[keep_mask])

        # sparse npz 행 필터링
        sparse_path = next(cache_dir.glob(f"cache_{domain}_sparse.npz"), None) \
                      or next(cache_dir.glob("*_sparse.npz"), None)
        if sparse_path and sparse_path.exists():
            mat = sp.load_npz(sparse_path)
            if mat.shape[0] == len(ids):
                sp.save_npz(sparse_path, mat[keep_mask])
            else:
                logger.warning(f"[prune] {sparse_path.name} 행 수 불일치 → 건너뜀")

        # asf_token_sets.json 리스트 필터링
        asf_path = cache_dir / "asf_token_sets.json"
        if asf_path.exists():
            try:
                asf_sets = json.loads(asf_path.read_text(encoding="utf-8"))
                if isinstance(asf_sets, list) and len(asf_sets) == len(ids):
                    new_sets = [s for s, k in zip(asf_sets, keep_mask) if k]
                    asf_path.write_text(json.dumps(new_sets, ensure_ascii=False),
                                        encoding="utf-8")
                else:
                    logger.warning(f"[prune] asf_token_sets 길이 불일치 → 건너뜀")
            except Exception as e:
                logger.warning(f"[prune] asf_token_sets 정리 실패: {e}")

        new_ids = [i for i, k in zip(ids, keep_mask) if k]
        _save_json(ids_path, {"ids": new_ids})

    # ChromaDB 삭제
    try:
        col = _get_col(col_name)
        col.delete(ids=list(stale))
    except Exception as e:
        logger.warning(f"[prune] ChromaDB 삭제 실패 ({col_name}): {e}")

    # Captions / page_images 삭제 (hard 모드)
    if hard and captions_dir:
        for key in stale:
            stem = Path(key).stem
            for sub in (captions_dir / stem,):
                if sub.is_dir():
                    import shutil
                    shutil.rmtree(sub, ignore_errors=True)

    # registry 갱신
    for k in stale:
        registry.pop(k, None)

    logger.info(f"[prune:{domain}] stale {len(stale)}개 제거")
    return registry, len(stale)
