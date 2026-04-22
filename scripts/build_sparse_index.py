"""scripts/build_sparse_index.py — BGE-M3 Sparse 인덱스 빌드 (v2 P2).

image / doc_page 각 도메인의 캡션을 BGE-M3 sparse 로 인코딩, CSR sparse matrix 저장.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from scipy import sparse as sp
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

from config import PATHS  # noqa: E402
from embedders.trichef import bgem3_sparse  # noqa: E402


def _load_caption(cap_dir: Path, stem: str) -> str:
    jp = cap_dir / f"{stem}.caption.json"
    tp = cap_dir / f"{stem}.txt"
    if jp.exists():
        try:
            d = json.loads(jp.read_text(encoding="utf-8"))
            # Sparse 채널에 가장 정보량 많은 조합
            parts = [d.get(k, "") for k in ("L1", "L2", "L3")]
            return " ".join(x for x in parts if x)
        except Exception:
            pass
    if tp.exists():
        return tp.read_text(encoding="utf-8")
    return ""


def build_image():
    cache = Path(PATHS["TRICHEF_IMG_CACHE"])
    ids = json.loads((cache / "img_ids.json").read_text(encoding="utf-8"))["ids"]
    cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    texts = [_load_caption(cap_dir, Path(i).stem) for i in ids]
    print(f"[image] N={len(texts)}  building sparse...")
    mat = _batch_encode(texts)
    sp.save_npz(cache / "cache_img_sparse.npz", mat)
    print(f"[image] nnz={mat.nnz}  saved {mat.shape}")


def build_doc():
    cache = Path(PATHS["TRICHEF_DOC_CACHE"])
    ids = json.loads((cache / "doc_page_ids.json").read_text(encoding="utf-8"))["ids"]
    extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])
    texts = []
    for i in ids:
        parts = Path(i).parts
        if len(parts) >= 3 and parts[0] == "page_images":
            doc_stem = parts[1]
            page_stem = Path(parts[2]).stem
            cap_dir = extract / "captions" / doc_stem
            texts.append(_load_caption(cap_dir, page_stem))
        else:
            texts.append("")
    print(f"[doc_page] N={len(texts)}  building sparse...")
    mat = _batch_encode(texts)
    sp.save_npz(cache / "cache_doc_page_sparse.npz", mat)
    print(f"[doc_page] nnz={mat.nnz}  saved {mat.shape}")


def _batch_encode(texts: list[str], batch: int = 32):
    parts = []
    for i in tqdm(range(0, len(texts), batch), desc="BGE-M3 Sparse"):
        chunk = texts[i:i+batch]
        parts.append(bgem3_sparse.embed_passage_sparse(chunk, batch_size=batch))
    return sp.vstack(parts).tocsr()


if __name__ == "__main__":
    build_image()
    build_doc()
