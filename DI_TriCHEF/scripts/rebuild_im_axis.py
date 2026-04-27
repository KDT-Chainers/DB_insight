"""DI_TriCHEF/scripts/rebuild_im_axis.py — Im 축 e5-large → BGE-M3 Dense 재구축.

기존 캡션(.txt)은 그대로 재사용. Re/Z 축은 건드리지 않음.
1. ids.json 기반 캡션 재로딩
2. BGE-M3 embed_passage (batch=32)
3. cache_*_Im.npy 덮어쓰기
4. Gram-Schmidt 재계산 (Im_perp, Z_perp)
5. ChromaDB upsert (chunked)
6. calibration 재계산
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

from config import PATHS, TRICHEF_CFG  # noqa: E402
from embedders.trichef import bgem3_caption_im  # noqa: E402
from services.trichef import tri_gs, calibration  # noqa: E402
from embedders.trichef.incremental_runner import _upsert_chroma  # noqa: E402


def _load_captions_image(ids: list[str]) -> list[str]:
    cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    out = []
    for i in ids:
        stem = Path(i).stem
        cp = cap_dir / f"{stem}.txt"
        out.append(cp.read_text(encoding="utf-8") if cp.exists() else "")
    return out


def _load_captions_doc(ids: list[str]) -> list[str]:
    extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])
    out = []
    for i in ids:
        # id = "page_images/<doc_stem>/p0000.jpg"
        parts = Path(i).parts
        if len(parts) >= 3 and parts[0] == "page_images":
            doc_stem = parts[1]
            page_stem = Path(parts[2]).stem
            cp = extract / "captions" / doc_stem / f"{page_stem}.txt"
            out.append(cp.read_text(encoding="utf-8") if cp.exists() else "")
        else:
            out.append("")
    return out


def _batch_embed(texts: list[str], batch: int = 32) -> np.ndarray:
    vecs = []
    for i in tqdm(range(0, len(texts), batch), desc="BGE-M3 Im"):
        chunk = texts[i:i+batch]
        vecs.append(bgem3_caption_im.embed_passage(chunk))
    return np.vstack(vecs).astype(np.float32)


def rebuild_domain(domain: str, cache_dir: Path, base_name_Re: str,
                   base_name_Im: str, base_name_Z: str, ids_file: str,
                   caption_loader, src_root: Path, col_name: str):
    Re = np.load(cache_dir / base_name_Re)
    Z  = np.load(cache_dir / base_name_Z)
    ids = json.loads((cache_dir / ids_file).read_text(encoding="utf-8"))["ids"]
    print(f"[{domain}] Re {Re.shape} Z {Z.shape} ids {len(ids)}")

    captions = caption_loader(ids)
    missing = sum(1 for c in captions if not c)
    print(f"[{domain}] 캡션 로드 완료 (빈 {missing}개)")

    Im_new = _batch_embed(captions)
    print(f"[{domain}] Im {Im_new.shape}")
    assert Im_new.shape[0] == Re.shape[0], "row count mismatch"

    np.save(cache_dir / base_name_Im, Im_new)
    print(f"[{domain}] saved {base_name_Im}")

    Im_perp, Z_perp = tri_gs.orthogonalize(Re, Im_new, Z)
    _upsert_chroma(col_name, ids, Re, Im_perp, Z_perp, src_root)
    calibration.calibrate_domain(domain, Re, Im_perp, Z_perp)
    print(f"[{domain}] ChromaDB + calibration OK")


def main():
    rebuild_domain(
        "image",
        Path(PATHS["TRICHEF_IMG_CACHE"]),
        "cache_img_Re_siglip2.npy", "cache_img_Im_e5cap.npy", "cache_img_Z_dinov2.npy",
        "img_ids.json", _load_captions_image,
        Path(PATHS["RAW_DB"]) / "Img",
        TRICHEF_CFG["COL_IMAGE"],
    )
    rebuild_domain(
        "doc_page",
        Path(PATHS["TRICHEF_DOC_CACHE"]),
        "cache_doc_page_Re.npy", "cache_doc_page_Im.npy", "cache_doc_page_Z.npy",
        "doc_page_ids.json", _load_captions_doc,
        Path(PATHS["TRICHEF_DOC_EXTRACT"]),
        TRICHEF_CFG["COL_DOC_PAGE"],
    )


if __name__ == "__main__":
    main()
