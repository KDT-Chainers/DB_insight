"""scripts/rebuild_doc_sparse_with_text.py — PDF 원문 텍스트 포함 sparse 재구축.

기존 BLIP 영어 캡션만으로는 한글 쿼리가 lexical 채널에 매칭되지 않음.
PyMuPDF(fitz)로 페이지별 실제 텍스트를 추출하여 캡션과 결합 후 sparse 재인덱싱.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import fitz
from scipy import sparse as sp
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

from config import PATHS  # noqa: E402
from embedders.trichef import bgem3_sparse  # noqa: E402
from embedders.trichef.doc_page_render import _sanitize  # noqa: E402


def _load_caption(cap_dir: Path, stem: str) -> str:
    jp = cap_dir / f"{stem}.caption.json"
    tp = cap_dir / f"{stem}.txt"
    if jp.exists():
        try:
            d = json.loads(jp.read_text(encoding="utf-8"))
            parts = [d.get(k, "") for k in ("L1", "L2", "L3")]
            return " ".join(x for x in parts if x)
        except Exception:
            pass
    if tp.exists():
        return tp.read_text(encoding="utf-8")
    return ""


def _build_stem_to_pdf() -> dict[str, Path]:
    cache = Path(PATHS["TRICHEF_DOC_CACHE"])
    registry = json.loads((cache / "registry.json").read_text(encoding="utf-8"))
    out: dict[str, Path] = {}
    for key, meta in registry.items():
        stem = _sanitize(Path(key).stem)
        out[stem] = Path(meta["abs"])
    return out


def _extract_pdf_pages_text(pdf_path: Path) -> dict[int, str]:
    """{page_idx: text}."""
    try:
        if pdf_path.stat().st_size == 0:
            return {}
        texts = {}
        with fitz.open(pdf_path) as doc:
            for i, pg in enumerate(doc):
                try:
                    texts[i] = pg.get_text("text") or ""
                except Exception:
                    texts[i] = ""
        return texts
    except Exception as e:
        print(f"[skip] {pdf_path.name}: {e}")
        return {}


def main():
    cache = Path(PATHS["TRICHEF_DOC_CACHE"])
    extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])
    ids = json.loads((cache / "doc_page_ids.json").read_text(encoding="utf-8"))["ids"]
    stem_to_pdf = _build_stem_to_pdf()
    print(f"PDFs in registry: {len(stem_to_pdf)}, ids: {len(ids)}")

    # 1. PDF별 텍스트 캐시
    pdf_text_cache: dict[str, dict[int, str]] = {}
    unique_stems = sorted({Path(i).parts[1] for i in ids if Path(i).parts[0] == "page_images"})
    for stem in tqdm(unique_stems, desc="PDF text extract"):
        pdf = stem_to_pdf.get(stem)
        if pdf and pdf.exists():
            pdf_text_cache[stem] = _extract_pdf_pages_text(pdf)
        else:
            pdf_text_cache[stem] = {}

    # 2. 페이지별 결합 텍스트
    texts: list[str] = []
    for i in ids:
        parts = Path(i).parts
        if len(parts) < 3 or parts[0] != "page_images":
            texts.append("")
            continue
        stem = parts[1]
        page_stem = Path(parts[2]).stem
        page_idx = int(page_stem.lstrip("p") or "0")
        cap = _load_caption(extract / "captions" / stem, page_stem)
        pdf_txt = pdf_text_cache.get(stem, {}).get(page_idx, "")
        # 캡션(영어) + 원문(주로 한글) 합산으로 cross-lingual 커버
        texts.append((cap + "\n" + pdf_txt).strip())
    print(f"조합 텍스트 준비 완료: {sum(1 for t in texts if t)}/{len(texts)} 비어있지 않음")

    # 3. sparse 재빌드
    parts = []
    batch = 32
    for i in tqdm(range(0, len(texts), batch), desc="BGE-M3 Sparse"):
        chunk = texts[i:i+batch]
        parts.append(bgem3_sparse.embed_passage_sparse(chunk, batch_size=batch,
                                                       max_length=2048))
    mat = sp.vstack(parts).tocsr()
    sp.save_npz(cache / "cache_doc_page_sparse.npz", mat)
    print(f"saved {mat.shape}  nnz={mat.nnz}")


if __name__ == "__main__":
    main()
