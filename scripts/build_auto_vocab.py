"""scripts/build_auto_vocab.py — image/doc 도메인 자동 어휘 사전 빌드 (v3 P3)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

from config import PATHS  # noqa: E402
from services.trichef import auto_vocab  # noqa: E402
from embedders.trichef.doc_page_render import _sanitize  # noqa: E402

import fitz  # noqa: E402


def _load_caption(cap_dir: Path, stem: str) -> str:
    jp = cap_dir / f"{stem}.caption.json"
    tp = cap_dir / f"{stem}.txt"
    if jp.exists():
        try:
            d = json.loads(jp.read_text(encoding="utf-8"))
            return " ".join(d.get(k, "") for k in ("L1", "L2", "L3") if d.get(k))
        except Exception:
            pass
    if tp.exists():
        return tp.read_text(encoding="utf-8")
    return ""


def build_image_vocab():
    cache = Path(PATHS["TRICHEF_IMG_CACHE"])
    ids = json.loads((cache / "img_ids.json").read_text(encoding="utf-8"))["ids"]
    cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    docs = [_load_caption(cap_dir, Path(i).stem) for i in ids]
    vocab = auto_vocab.build_vocab(docs, min_df=2, max_df_ratio=0.5, top_k=5000)
    auto_vocab.save_vocab(cache / "auto_vocab.json", vocab)
    print(f"[image] vocab {len(vocab)} 저장")


def build_doc_vocab():
    cache = Path(PATHS["TRICHEF_DOC_CACHE"])
    extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])
    ids = json.loads((cache / "doc_page_ids.json").read_text(encoding="utf-8"))["ids"]
    registry = json.loads((cache / "registry.json").read_text(encoding="utf-8"))
    stem_to_pdf = {_sanitize(Path(k).stem): Path(v["abs"]) for k, v in registry.items()}

    pdf_text: dict[str, dict[int, str]] = {}
    unique_stems = sorted({Path(i).parts[1] for i in ids if Path(i).parts[0] == "page_images"})
    for stem in tqdm(unique_stems, desc="PDF text"):
        pdf = stem_to_pdf.get(stem)
        if not pdf or not pdf.exists() or pdf.stat().st_size == 0:
            pdf_text[stem] = {}
            continue
        try:
            with fitz.open(pdf) as d:
                pdf_text[stem] = {i: p.get_text("text") or "" for i, p in enumerate(d)}
        except Exception:
            pdf_text[stem] = {}

    docs = []
    for i in ids:
        parts = Path(i).parts
        if len(parts) < 3 or parts[0] != "page_images":
            docs.append("")
            continue
        stem = parts[1]
        page_stem = Path(parts[2]).stem
        page_idx = int(page_stem.lstrip("p") or "0")
        cap = _load_caption(extract / "captions" / stem, page_stem)
        txt = pdf_text.get(stem, {}).get(page_idx, "")
        docs.append(cap + "\n" + txt)

    vocab = auto_vocab.build_vocab(docs, min_df=3, max_df_ratio=0.3, top_k=15000)
    auto_vocab.save_vocab(cache / "auto_vocab.json", vocab)
    print(f"[doc_page] vocab {len(vocab)} 저장")


if __name__ == "__main__":
    build_image_vocab()
    build_doc_vocab()
