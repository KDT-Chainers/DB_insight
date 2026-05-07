"""DI_TriCHEF/scripts/migrate_stem_hash.py — H-2: 기존 page_images/captions 를 hash-suffix stem 으로 이관.

변경 대상:
  [Doc]
  - TRICHEF_DOC_EXTRACT/page_images/<old_stem>/   →  /<new_stem_key>/
  - TRICHEF_DOC_EXTRACT/captions/<old_stem>/      →  /<new_stem_key>/
  - TRICHEF_DOC_CACHE/doc_page_ids.json           (id prefix rewrite)
  - ChromaDB COL_DOC_PAGE                         (old id → new id)

  [Image]
  - TRICHEF_IMG_EXTRACT/captions/<old_stem>.{caption.json,txt} → /<new_stem_key>.*
    (ids/ChromaDB 는 rel_key 그대로라 변경 없음 — 캡션 파일명만 이관)

보존(무재임베딩):
  - cache_doc_page_Re.npy / Im.npy / Z.npy
  - cache_doc_page_sparse.npz
  - asf_token_sets.json
  - calibration.json
  (positional order 유지)

사용법:
  python DI_TriCHEF/scripts/migrate_stem_hash.py --dry-run
  python DI_TriCHEF/scripts/migrate_stem_hash.py
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

from config import PATHS, TRICHEF_CFG  # noqa: E402
from embedders.trichef.doc_page_render import _sanitize, stem_key_for  # noqa: E402


def build_mapping(registry: dict) -> dict[str, str]:
    """old_stem (_sanitize(Path(key).stem))  →  new_stem_key (stem_key_for(key))."""
    mapping: dict[str, str] = {}
    collisions: dict[str, list[str]] = {}
    for key in registry:
        old = _sanitize(Path(key).stem)
        new = stem_key_for(key)
        if old in mapping and mapping[old] != new:
            collisions.setdefault(old, [mapping[old]]).append(new)
        mapping[old] = new
    if collisions:
        print(f"[migrate] stem 충돌 감지: {len(collisions)} 건 — 마지막 registry 항목 기준으로 매핑")
        for k, vs in collisions.items():
            print(f"  {k!r} → {vs}")
    return mapping


def rename_subdirs(parent: Path, mapping: dict[str, str], dry: bool) -> int:
    if not parent.exists():
        return 0
    n = 0
    for old, new in mapping.items():
        if old == new:
            continue
        src = parent / old
        dst = parent / new
        if not src.exists() or dst.exists():
            continue
        print(f"  mv {src.name} → {dst.name}")
        if not dry:
            src.rename(dst)
        n += 1
    return n


def rewrite_ids(cache: Path, mapping: dict[str, str], dry: bool) -> tuple[int, list[str]]:
    ids_path = cache / "doc_page_ids.json"
    if not ids_path.exists():
        return 0, []
    ids = json.loads(ids_path.read_text(encoding="utf-8"))["ids"]
    new_ids: list[str] = []
    changed = 0
    for i in ids:
        parts = Path(i).parts
        if len(parts) >= 3 and parts[0] == "page_images":
            old_stem = parts[1]
            new_stem = mapping.get(old_stem, old_stem)
            if new_stem != old_stem:
                new_i = "/".join(["page_images", new_stem, *parts[2:]])
                new_ids.append(new_i)
                changed += 1
                continue
        new_ids.append(i)
    print(f"[ids] 변경 {changed}/{len(ids)}")
    if not dry and changed:
        ids_path.write_text(json.dumps({"ids": new_ids}, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    return changed, new_ids


def update_chroma(col_name: str, old_ids: list[str], new_ids: list[str], dry: bool):
    if not old_ids or old_ids == new_ids:
        return
    import chromadb
    from chromadb.config import Settings
    client = chromadb.PersistentClient(
        path=str(Path(PATHS["TRICHEF_CHROMA"])),
        settings=Settings(anonymized_telemetry=False),
    )
    col = client.get_or_create_collection(name=col_name, metadata={"hnsw:space": "cosine"})
    diff = [(o, n) for o, n in zip(old_ids, new_ids) if o != n]
    print(f"[chroma:{col_name}] id 변경 {len(diff)}")
    if dry or not diff:
        return
    CHUNK = 2000
    for s in range(0, len(diff), CHUNK):
        batch = diff[s:s+CHUNK]
        got = col.get(ids=[o for o, _ in batch], include=["embeddings", "metadatas"])
        # got 의 순서가 요청 순서와 다를 수 있음 → id→vec/meta 매핑
        id_to_vec = dict(zip(got["ids"], got["embeddings"]))
        id_to_meta = dict(zip(got["ids"], got["metadatas"]))
        new_batch_ids = []
        new_batch_vecs = []
        new_batch_meta = []
        for o, n in batch:
            if o not in id_to_vec:
                continue
            meta = dict(id_to_meta.get(o) or {})
            meta["id"] = n
            if "path" in meta:
                meta["path"] = meta["path"].replace(o, n)
            new_batch_ids.append(n)
            new_batch_vecs.append(id_to_vec[o])
            new_batch_meta.append(meta)
        col.delete(ids=[o for o, _ in batch])
        if new_batch_ids:
            col.upsert(ids=new_batch_ids, embeddings=new_batch_vecs, metadatas=new_batch_meta)


def migrate_image_captions(dry: bool) -> int:
    """이미지 캡션 파일명 이관: <old_stem>.caption.json → <new_stem_key>.caption.json."""
    img_cache = Path(PATHS["TRICHEF_IMG_CACHE"])
    img_cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    img_reg_path = img_cache / "registry.json"
    if not img_reg_path.exists() or not img_cap_dir.exists():
        print("[image] registry/captions 없음 — 스킵")
        return 0
    img_reg = json.loads(img_reg_path.read_text(encoding="utf-8"))
    renamed = 0
    for key in img_reg:
        # image 캡션 원본 파일명은 `img_path.stem` (sanitize 미적용) 기준
        old = Path(key).stem
        new = stem_key_for(key)
        if old == new:
            continue
        for ext in (".caption.json", ".txt"):
            src = img_cap_dir / f"{old}{ext}"
            dst = img_cap_dir / f"{new}{ext}"
            if src.exists() and not dst.exists():
                print(f"  mv {src.name} → {dst.name}")
                if not dry:
                    src.rename(dst)
                renamed += 1
    print(f"[image] 캡션 파일 이관 {renamed}개")
    return renamed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run

    cache = Path(PATHS["TRICHEF_DOC_CACHE"])
    extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])
    reg_path = cache / "registry.json"

    print("\n=== [Image] 캡션 파일명 이관 ===")
    migrate_image_captions(dry)

    print("\n=== [Doc] page_images/captions/ids/Chroma 이관 ===")
    if not reg_path.exists():
        print("doc registry.json 없음 — doc 이관 스킵")
        print("\n완료" + (" (dry-run)" if dry else ""))
        return

    registry = json.loads(reg_path.read_text(encoding="utf-8"))
    print(f"registry entries: {len(registry)}")
    mapping = build_mapping(registry)
    changes = sum(1 for o, n in mapping.items() if o != n)
    print(f"stem 이관 대상: {changes}/{len(mapping)}  (dry_run={dry})")
    if changes == 0:
        print("변경 대상 없음.")
        return

    print("\n[1/4] page_images 디렉토리 리네임")
    rename_subdirs(extract / "page_images", mapping, dry)

    print("\n[2/4] captions 디렉토리 리네임")
    rename_subdirs(extract / "captions", mapping, dry)

    print("\n[3/4] doc_page_ids.json 재작성")
    ids_path = cache / "doc_page_ids.json"
    old_ids = json.loads(ids_path.read_text(encoding="utf-8"))["ids"] if ids_path.exists() else []
    _, new_ids = rewrite_ids(cache, mapping, dry)

    print("\n[4/4] ChromaDB id 이관")
    if new_ids:
        update_chroma(TRICHEF_CFG["COL_DOC_PAGE"], old_ids, new_ids, dry)

    print("\n완료" + (" (dry-run)" if dry else ""))


if __name__ == "__main__":
    main()
