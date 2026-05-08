"""scripts/remove_file_from_index.py — 통합 파일 인덱스 제거 도구.

5개 도메인(image/doc/movie/music/bgm) 단건 파일을 인덱스에서 완전 제거.
모든 캐시 파일 (npy/npz/jsonl/json) 정합성 유지하며 행 제거.

지원 도메인 + 캐시 파일:
  image  → cache_img_Re/Im_L1/L2/L3/Im_e5cap/Z, sparse, asf_token_sets, ids
  doc    → cache_doc_*, asf_token_sets, registry
  movie  → cache_movie_Re/Im/Z, sparse, ids, segments
  music  → cache_music_*, ids, segments
  bgm    → cache_audio_clap, audio_meta

자동 백업, 행 정합성 보장, dry-run 지원.

사용:
  python scripts/remove_file_from_index.py --domain image --pattern "고양이"
  python scripts/remove_file_from_index.py --domain movie --pattern "NGC 코스모스 E13"
  python scripts/remove_file_from_index.py --domain image --pattern "햄버거" --dry-run

⚠️ 적용 후 Flask 재시작 필요 (캐시 메모리 갱신).
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))


# 도메인별 인덱스 파일 매핑
DOMAIN_CONFIG = {
    "image": {
        "ids_file": "img_ids.json",
        "ids_key": "ids",
        "row_files": [
            "cache_img_Re_siglip2.npy",
            "cache_img_Im_L1.npy",
            "cache_img_Im_L2.npy",
            "cache_img_Im_L3.npy",
            "cache_img_Im_e5cap.npy",
            "cache_img_Im.npy",
            "cache_img_Z_dinov2.npy",
        ],
        "row_sparse": ["cache_img_sparse.npz"],
        "row_json_list": ["asf_token_sets.json"],
        "registry": "registry.json",
        "captions_jsonl": "captions_triple.jsonl",
        "captions_dir": "captions",
        "captions_dir_path_key": "TRICHEF_IMG_EXTRACT",
        "cache_path_key": "TRICHEF_IMG_CACHE",
    },
    "doc": {
        "ids_file": "doc_ids.json",
        "ids_key": "ids",
        "row_files": [
            "cache_doc_page_Re.npy",
            "cache_doc_page_Im.npy",
            "cache_doc_page_Im_body.npy",
            "cache_doc_page_Z.npy",
        ],
        "row_sparse": ["cache_doc_page_sparse.npz"],
        "row_json_list": ["asf_token_sets.json"],
        "registry": "registry.json",
        "cache_path_key": "TRICHEF_DOC_CACHE",
    },
    "movie": {
        "ids_file": "movie_ids.json",
        "ids_key": None,  # list directly
        "row_files": [
            "cache_movie_Re.npy",
            "cache_movie_Im.npy",
            "cache_movie_Z.npy",
        ],
        "row_sparse": ["cache_movie_sparse.npz"],
        "row_json_list": ["movie_token_sets.json"],
        "registry": "registry.json",
        "cache_path_key": "TRICHEF_MOVIE_CACHE",
    },
    "music": {
        "ids_file": "music_ids.json",
        "ids_key": None,
        "row_files": [
            "cache_music_Re.npy",
            "cache_music_Im.npy",
            "cache_music_Z.npy",
        ],
        "row_sparse": ["cache_music_sparse.npz"],
        "row_json_list": ["music_token_sets.json"],
        "registry": "registry.json",
        "cache_path_key": "TRICHEF_MUSIC_CACHE",
    },
    "bgm": {
        "ids_file": "audio_meta.json",  # different format — list of dicts
        "ids_key": None,
        "row_files": ["cache_audio_clap.npy"],
        "row_sparse": [],
        "row_json_list": [],
        "registry": None,
        "cache_path_key": "EMBEDDED_DB",  # custom path: EMBEDDED_DB/Bgm
        "cache_subdir": "Bgm",
    },
}


def _resolve_cache_dir(domain: str) -> Path:
    from config import PATHS, EMBEDDED_DB
    cfg = DOMAIN_CONFIG[domain]
    if "cache_subdir" in cfg:
        return EMBEDDED_DB / cfg["cache_subdir"]
    return Path(PATHS[cfg["cache_path_key"]])


def _load_ids(cache_dir: Path, cfg: dict) -> tuple[list, dict | list]:
    p = cache_dir / cfg["ids_file"]
    if not p.exists():
        return [], None
    raw = json.loads(p.read_text(encoding="utf-8"))
    key = cfg.get("ids_key")
    if key and isinstance(raw, dict):
        return raw.get(key, []), raw
    if isinstance(raw, list):
        return raw, raw
    return [], raw


def _save_ids(p: Path, ids: list, raw_container, cfg: dict):
    key = cfg.get("ids_key")
    if key and isinstance(raw_container, dict):
        raw_container[key] = ids
        p.write_text(json.dumps(raw_container, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        p.write_text(json.dumps(ids, indent=2, ensure_ascii=False), encoding="utf-8")


def _id_matches(item, pattern: str) -> bool:
    """ID 가 파일 이름 string 또는 dict (BGM audio_meta) 인 경우 모두 처리."""
    if isinstance(item, str):
        return pattern in item
    if isinstance(item, dict):
        # audio_meta.json: dict with "filename", "path", etc.
        for k in ("filename", "file_name", "name", "path", "abs", "key"):
            v = item.get(k)
            if isinstance(v, str) and pattern in v:
                return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True, choices=list(DOMAIN_CONFIG.keys()),
                        help="대상 도메인")
    parser.add_argument("--pattern", required=True,
                        help="ID/파일명 부분 매칭")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = DOMAIN_CONFIG[args.domain]
    cache_dir = _resolve_cache_dir(args.domain)
    if not cache_dir.exists():
        logger.error(f"Cache dir not found: {cache_dir}")
        return

    logger.info(f"=== Domain: {args.domain}, Pattern: {args.pattern!r} ===")
    logger.info(f"Cache dir: {cache_dir}")

    # 1. Load ids
    ids_path = cache_dir / cfg["ids_file"]
    ids, raw_container = _load_ids(cache_dir, cfg)
    if not ids:
        logger.error(f"No ids loaded from {ids_path}")
        return
    logger.info(f"Total ids: {len(ids)}")

    # 2. Find matching indices
    keep_indices = []
    remove_indices = []
    for i, _id in enumerate(ids):
        if _id_matches(_id, args.pattern):
            remove_indices.append(i)
        else:
            keep_indices.append(i)

    if not remove_indices:
        logger.info("No matching ids — done")
        return

    logger.info(f"Match: {len(remove_indices)} ids")
    for idx in remove_indices[:10]:
        item = ids[idx]
        if isinstance(item, str):
            logger.info(f"  [{idx}] {item}")
        else:
            logger.info(f"  [{idx}] {(item.get('filename') or item.get('path') or item.get('key') or '?')}")
    if len(remove_indices) > 10:
        logger.info(f"  ... +{len(remove_indices) - 10} more")

    if args.dry_run:
        logger.info("\n[DRY RUN] No changes applied.")
        return

    # 3. Backup
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = cache_dir / f"_bak_remove_{ts}"
    bak.mkdir(exist_ok=True)
    logger.info(f"\nBackup dir: {bak}")

    # 4. Update ids file
    shutil.copy2(ids_path, bak / cfg["ids_file"])
    new_ids = [ids[i] for i in keep_indices]
    _save_ids(ids_path, new_ids, raw_container, cfg)
    logger.info(f"  {cfg['ids_file']}: {len(ids)} -> {len(new_ids)}")

    # 5. Update row-based files (npy)
    import numpy as np
    for fn in cfg.get("row_files", []):
        p = cache_dir / fn
        if not p.exists():
            continue
        arr = np.load(str(p))
        if arr.shape[0] != len(ids):
            logger.warning(f"  {fn}: shape[0]={arr.shape[0]} != ids={len(ids)} -- skip")
            continue
        shutil.copy2(p, bak / fn)
        new_arr = arr[keep_indices]
        np.save(str(p), new_arr)
        logger.info(f"  {fn}: {arr.shape} -> {new_arr.shape}")

    # 6. Update sparse (npz)
    try:
        import scipy.sparse as sp
    except Exception:
        sp = None
    for fn in cfg.get("row_sparse", []):
        p = cache_dir / fn
        if not p.exists() or sp is None:
            continue
        m = sp.load_npz(str(p))
        if m.shape[0] != len(ids):
            logger.warning(f"  {fn}: shape[0]={m.shape[0]} != ids={len(ids)} -- skip")
            continue
        shutil.copy2(p, bak / fn)
        new_m = m[keep_indices, :]
        sp.save_npz(str(p), new_m)
        logger.info(f"  {fn}: {m.shape} -> {new_m.shape}")

    # 7. Update row-based JSON lists (asf_token_sets etc)
    for fn in cfg.get("row_json_list", []):
        p = cache_dir / fn
        if not p.exists():
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(obj, list) or len(obj) != len(ids):
                logger.warning(f"  {fn}: not row-aligned list -- skip")
                continue
            shutil.copy2(p, bak / fn)
            new_obj = [obj[i] for i in keep_indices]
            p.write_text(json.dumps(new_obj, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"  {fn}: {len(obj)} -> {len(new_obj)}")
        except Exception as e:
            logger.warning(f"  {fn}: failed -- {e}")

    # 8. Update captions_triple.jsonl (image only)
    if "captions_jsonl" in cfg:
        p = cache_dir / cfg["captions_jsonl"]
        if p.exists():
            shutil.copy2(p, bak / cfg["captions_jsonl"])
            removed_ids = {ids[i] for i in remove_indices if isinstance(ids[i], str)}
            new_lines = []
            n_removed = 0
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if obj.get("key") in removed_ids:
                            n_removed += 1
                            continue
                    except Exception:
                        pass
                    new_lines.append(line)
            p.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            logger.info(f"  {cfg['captions_jsonl']}: removed {n_removed}")

    # 9. Update registry
    if cfg.get("registry"):
        p = cache_dir / cfg["registry"]
        if p.exists():
            shutil.copy2(p, bak / cfg["registry"])
            try:
                reg = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(reg, dict):
                    keys_to_remove = [k for k in reg if any(args.pattern in str(rid) for rid in [ids[i] for i in remove_indices if isinstance(ids[i], str)] if isinstance(rid, str)) or args.pattern in k]
                    for k in keys_to_remove:
                        reg.pop(k, None)
                    p.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
                    logger.info(f"  {cfg['registry']}: removed {len(keys_to_remove)}")
            except Exception as e:
                logger.warning(f"  {cfg['registry']}: {e}")

    # 10. Caption cache files (image only, plain text per stem)
    if "captions_dir" in cfg and "captions_dir_path_key" in cfg:
        from config import PATHS
        cap_root = Path(PATHS[cfg["captions_dir_path_key"]]) / cfg["captions_dir"]
        n_deleted = 0
        if cap_root.exists():
            for i in remove_indices:
                rid = ids[i]
                if isinstance(rid, str):
                    stem = Path(rid).stem
                    for ext in [".txt", ".qwen", ".caption.json"]:
                        f = cap_root / f"{stem}{ext}"
                        if f.exists():
                            try:
                                f.unlink()
                                n_deleted += 1
                            except Exception:
                                pass
        logger.info(f"  caption cache files: removed {n_deleted}")

    logger.info(f"\nDone. Backup: {bak}")
    logger.info("Note: Flask 재시작 필요 (캐시 메모리 갱신).")


if __name__ == "__main__":
    main()
