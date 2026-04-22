"""embedders/trichef/incremental_runner.py — 증분 임베딩 러너.

IndexRegistry 에 저장된 파일 SHA-256 해시를 비교하여 신규/수정 파일만 임베딩한다.
3축 캐시 (.npy) 누적 append + ChromaDB upsert + calibration 재보정 트리거.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import chromadb
import numpy as np
from chromadb.config import Settings
from tqdm import tqdm

from config import PATHS, TRICHEF_CFG
from embedders.trichef import siglip2_re, e5_caption_im, dinov2_z, qwen_caption, doc_page_render
from services.trichef import tri_gs, calibration

logger = logging.getLogger(__name__)


@dataclass
class IncrementalResult:
    domain: str
    new: int
    existing: int
    total: int


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_registry(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_registry(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_trichef_collection(name: str):
    """TRI-CHEF 전용 ChromaDB 컬렉션 반환 (3200d concat 벡터용)."""
    chroma_path = Path(PATHS["TRICHEF_CHROMA"])
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(chroma_path),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def _upsert_chroma(collection: str, ids: list[str],
                   Re: np.ndarray, Im_perp: np.ndarray, Z_perp: np.ndarray,
                   src_root: Path) -> None:
    """ChromaDB 에 Re||Im⊥||Z⊥⊥ concat 벡터로 upsert.

    ChromaDB 는 빠른 prefilter 용으로만 사용.
    메인 점수는 .npy 원본으로 Hermitian 계산.
    """
    col = _get_trichef_collection(collection)
    metadatas = [{"path": str(src_root / i), "id": i} for i in ids]
    embeds = np.hstack([Re, Im_perp, Z_perp]).astype(np.float32)
    col.upsert(ids=ids, embeddings=embeds.tolist(), metadatas=metadatas)


# ── 이미지 도메인 ────────────────────────────────────────────────────────────
def run_image_incremental() -> IncrementalResult:
    raw_dir   = Path(PATHS["RAW_DB"]) / "Img"
    cache_dir = Path(PATHS["TRICHEF_IMG_CACHE"])
    reg_path  = cache_dir / "registry.json"
    registry  = _load_registry(reg_path)

    img_files = sorted(
        p for p in raw_dir.rglob("*")
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    existing_count = len(registry)
    new_files: list[Path] = []
    for p in img_files:
        key = str(p.relative_to(raw_dir)).replace("\\", "/")
        sha = _sha256(p)
        if registry.get(key, {}).get("sha") != sha:
            new_files.append(p)
            registry[key] = {"sha": sha, "abs": str(p)}

    logger.info(f"[img_inc] 기존={existing_count}, 신규={len(new_files)}")
    if not new_files:
        return IncrementalResult("image", 0, existing_count, existing_count)

    # 1. 캡션 생성 (Im 축 원천)
    cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    cap_dir.mkdir(parents=True, exist_ok=True)
    captions: list[str] = []
    for p in tqdm(new_files, desc="Qwen caption"):
        cp = cap_dir / f"{p.stem}.txt"
        if cp.exists():
            captions.append(cp.read_text(encoding="utf-8"))
        else:
            c = qwen_caption.caption(p)
            cp.write_text(c, encoding="utf-8")
            captions.append(c)

    # 2. 3축 임베딩
    new_Re = siglip2_re.embed_images(new_files)
    new_Im = e5_caption_im.embed_passage(captions)
    new_Z  = dinov2_z.embed_images(new_files)

    # 3. 누적 concat
    def _merge(name: str, new_vec: np.ndarray) -> np.ndarray:
        p = cache_dir / name
        if p.exists():
            prev = np.load(p)
            merged = np.vstack([prev, new_vec])
        else:
            merged = new_vec
        np.save(p, merged)
        return merged

    Re_all = _merge("cache_img_Re_siglip2.npy", new_Re)
    Im_all = _merge("cache_img_Im_e5cap.npy",   new_Im)
    Z_all  = _merge("cache_img_Z_dinov2.npy",   new_Z)

    # ids 파일 갱신
    ids_path = cache_dir / "img_ids.json"
    prev_ids = _load_registry(ids_path).get("ids", []) if ids_path.exists() else []
    new_ids  = [str(p.relative_to(raw_dir)).replace("\\", "/") for p in new_files]
    all_ids  = prev_ids + new_ids
    ids_path.write_text(json.dumps({"ids": all_ids}, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # 4. Gram-Schmidt 직교화 + ChromaDB upsert
    Im_perp, Z_perp = tri_gs.orthogonalize(Re_all, Im_all, Z_all)
    _upsert_chroma(TRICHEF_CFG["COL_IMAGE"], all_ids, Re_all, Im_perp, Z_perp, raw_dir)

    # 5. calibration 재보정
    calibration.calibrate_domain("image", Re_all, Im_perp, Z_perp)

    # 6. registry save
    _save_registry(reg_path, registry)

    return IncrementalResult("image", len(new_files), existing_count, len(all_ids))


# ── 문서 도메인 (doc_page) ──────────────────────────────────────────────────
def run_doc_incremental() -> IncrementalResult:
    raw_dir   = Path(PATHS["RAW_DB"]) / "Doc"
    cache_dir = Path(PATHS["TRICHEF_DOC_CACHE"])
    reg_path  = cache_dir / "registry.json"
    registry  = _load_registry(reg_path)

    doc_files = sorted(
        p for p in raw_dir.rglob("*")
        if p.suffix.lower() in {".pdf", ".docx", ".hwp", ".xlsx", ".txt"}
    )

    new_docs = [
        p for p in doc_files
        if registry.get(str(p.relative_to(raw_dir)).replace("\\", "/"),
                        {}).get("sha") != _sha256(p)
    ]
    logger.info(f"[doc_inc] 기존={len(registry)}, 신규={len(new_docs)}")

    if not new_docs:
        return IncrementalResult("document", 0, len(registry), len(registry))

    # 1. PDF → 페이지 JPEG 렌더
    all_page_imgs: list[Path] = []
    all_page_captions: list[str] = []
    for p in tqdm(new_docs, desc="PDF render + caption"):
        if p.suffix.lower() != ".pdf":
            continue
        pages = doc_page_render.render_pdf(p)
        cap_dir = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "captions" / p.stem
        cap_dir.mkdir(parents=True, exist_ok=True)
        for pg in pages:
            cp = cap_dir / f"{pg.stem}.txt"
            if cp.exists():
                cap = cp.read_text(encoding="utf-8")
            else:
                cap = qwen_caption.caption(pg)
                cp.write_text(cap, encoding="utf-8")
            all_page_imgs.append(pg)
            all_page_captions.append(cap)

    if not all_page_imgs:
        # PDF 외 파일만 있는 경우 registry 만 갱신
        for p in new_docs:
            key = str(p.relative_to(raw_dir)).replace("\\", "/")
            registry[key] = {"sha": _sha256(p), "abs": str(p)}
        _save_registry(reg_path, registry)
        return IncrementalResult("document", len(new_docs), len(registry), len(registry))

    # 2. 3축 임베딩 (doc_page)
    new_Re = siglip2_re.embed_images(all_page_imgs)
    new_Im = e5_caption_im.embed_passage(all_page_captions)
    new_Z  = dinov2_z.embed_images(all_page_imgs)

    # 3. 캐시 누적
    def _merge(name: str, new_vec: np.ndarray) -> np.ndarray:
        p = cache_dir / name
        if p.exists():
            prev = np.load(p)
            merged = np.vstack([prev, new_vec])
        else:
            merged = new_vec
        np.save(p, merged)
        return merged

    Re_all = _merge("cache_doc_page_Re.npy", new_Re)
    Im_all = _merge("cache_doc_page_Im.npy", new_Im)
    Z_all  = _merge("cache_doc_page_Z.npy",  new_Z)

    # 4. ids 갱신
    ids_path = cache_dir / "doc_page_ids.json"
    prev = _load_registry(ids_path).get("ids", []) if ids_path.exists() else []
    new_ids = [
        str(pg.relative_to(Path(PATHS["TRICHEF_DOC_EXTRACT"]))).replace("\\", "/")
        for pg in all_page_imgs
    ]
    all_ids = prev + new_ids
    ids_path.write_text(json.dumps({"ids": all_ids}, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    Im_perp, Z_perp = tri_gs.orthogonalize(Re_all, Im_all, Z_all)
    _upsert_chroma(TRICHEF_CFG["COL_DOC_PAGE"], all_ids, Re_all, Im_perp, Z_perp,
                   Path(PATHS["TRICHEF_DOC_EXTRACT"]))
    calibration.calibrate_domain("doc_page", Re_all, Im_perp, Z_perp)

    # 5. registry save
    for p in new_docs:
        key = str(p.relative_to(raw_dir)).replace("\\", "/")
        registry[key] = {"sha": _sha256(p), "abs": str(p)}
    _save_registry(reg_path, registry)

    return IncrementalResult("document", len(new_docs), len(registry), len(registry))
