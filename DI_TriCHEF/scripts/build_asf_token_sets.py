"""DI_TriCHEF/scripts/build_asf_token_sets.py — 문서별 vocab-token 집합 precompute (v3 P4).

ASF 필터가 런타임에서 재토큰화하지 않도록 {token: idf} 리스트를 디스크에 저장.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import fitz
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

from config import PATHS  # noqa: E402
from embedders.trichef.caption_io import load_caption as _load_caption, page_idx_from_stem  # noqa: E402
from services.trichef import asf_filter, auto_vocab  # noqa: E402
from services.trichef.lexical_rebuild import resolve_doc_pdf_map  # noqa: E402


def build_image():
    cache = Path(PATHS["TRICHEF_IMG_CACHE"])
    vocab = auto_vocab.load_vocab(cache / "auto_vocab.json")
    ids = json.loads((cache / "img_ids.json").read_text(encoding="utf-8"))["ids"]
    cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    docs = [_load_caption(cap_dir, Path(i).stem) for i in ids]
    sets = asf_filter.build_doc_token_sets(docs, vocab)
    asf_filter.save_token_sets(cache / "asf_token_sets.json", sets)
    nonempty = sum(1 for s in sets if s)
    print(f"[image] token-sets {nonempty}/{len(sets)} 저장")


def build_doc():
    cache = Path(PATHS["TRICHEF_DOC_CACHE"])
    extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])
    vocab = auto_vocab.load_vocab(cache / "auto_vocab.json")
    ids = json.loads((cache / "doc_page_ids.json").read_text(encoding="utf-8"))["ids"]
    stem_to_pdf = resolve_doc_pdf_map()

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
        page_idx = page_idx_from_stem(page_stem)
        cap = _load_caption(extract / "captions" / stem, page_stem)
        txt = pdf_text.get(stem, {}).get(page_idx, "")
        docs.append(cap + "\n" + txt)

    sets = asf_filter.build_doc_token_sets(docs, vocab)
    asf_filter.save_token_sets(cache / "asf_token_sets.json", sets)
    nonempty = sum(1 for s in sets if s)
    print(f"[doc_page] token-sets {nonempty}/{len(sets)} 저장")


if __name__ == "__main__":
    build_image()
    build_doc()
