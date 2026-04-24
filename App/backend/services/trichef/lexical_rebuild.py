"""services/trichef/lexical_rebuild.py — vocab/sparse/asf 재구축 공유 로직 (C-2 후반).

신규 파일이 incremental_runner 로 임베딩된 후, 이 모듈의 함수를 호출하여
lexical/ASF 채널에 누락되지 않도록 한다.

공유 정의:
  - image: 캡션만 사용 (원문 텍스트 없음)
  - doc_page: 캡션 + PDF 페이지 원문 합산 (cross-lingual KR/EN 커버)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import fitz
from scipy import sparse as sp
from tqdm import tqdm

from config import PATHS
from embedders.trichef import bgem3_sparse
from embedders.trichef.caption_io import load_caption, page_idx_from_stem
from embedders.trichef.doc_page_render import _sanitize, stem_key_for
from services.trichef import asf_filter, auto_vocab

logger = logging.getLogger(__name__)


# ── 공용 유틸 ───────────────────────────────────────────────────────────
def _encode_sparse(texts: list[str], batch: int = 32, max_length: int | None = None):
    parts = []
    for i in tqdm(range(0, len(texts), batch), desc="BGE-M3 Sparse"):
        chunk = texts[i:i + batch]
        kw = {"batch_size": batch}
        if max_length is not None:
            kw["max_length"] = max_length
        parts.append(bgem3_sparse.embed_passage_sparse(chunk, **kw))
    return sp.vstack(parts).tocsr()


def resolve_doc_pdf_map() -> dict[str, Path]:
    """doc registry → {sanitized_stem: resolved_pdf_path} (converted_pdf 우선)."""
    from embedders.trichef.doc_ingest import converted_pdf_path
    _CONV_EXT = {".hwp", ".hwpx", ".docx", ".doc", ".pptx", ".ppt",
                 ".xlsx", ".xls", ".odt", ".odp", ".ods", ".rtf"}
    cache = Path(PATHS["TRICHEF_DOC_CACHE"])
    reg_path = cache / "registry.json"
    if not reg_path.exists():
        return {}
    registry = json.loads(reg_path.read_text(encoding="utf-8"))
    out: dict[str, Path] = {}
    for key, meta in registry.items():
        # 신규 규칙(hash suffix) 우선. 마이그레이션 전 데이터는 레거시 stem 도 fallback.
        stem = stem_key_for(key)
        if stem in out:
            logger.warning(f"[lexical_rebuild] stem 충돌: {stem!r} - {key!r} 무시")
            continue
        src = Path(meta["abs"])
        if src.suffix.lower() in _CONV_EXT:
            conv = converted_pdf_path(src)
            if conv is not None:
                out[stem] = conv
                continue
        out[stem] = src
    return out


def _doc_page_texts(ids: list[str]) -> list[str]:
    """doc_page_ids → 페이지별 (캡션 + PDF원문) 텍스트 리스트."""
    extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])
    stem_to_pdf = resolve_doc_pdf_map()

    pdf_text: dict[str, dict[int, str]] = {}
    unique_stems = sorted({Path(i).parts[1] for i in ids
                           if Path(i).parts[0] == "page_images" and len(Path(i).parts) >= 3})
    for stem in tqdm(unique_stems, desc="PDF text"):
        pdf = stem_to_pdf.get(stem)
        if not pdf or not pdf.exists() or pdf.stat().st_size == 0:
            pdf_text[stem] = {}
            continue
        try:
            with fitz.open(pdf) as d:
                pdf_text[stem] = {i: (p.get_text("text") or "") for i, p in enumerate(d)}
        except Exception as e:
            logger.warning(f"[lexical_rebuild] PDF open 실패 {pdf.name}: {e}")
            pdf_text[stem] = {}

    texts: list[str] = []
    for i in ids:
        parts = Path(i).parts
        if len(parts) < 3 or parts[0] != "page_images":
            texts.append("")
            continue
        stem = parts[1]
        page_stem = Path(parts[2]).stem
        cap = load_caption(extract / "captions" / stem, page_stem)
        pdf_txt = pdf_text.get(stem, {}).get(page_idx_from_stem(page_stem), "")
        texts.append((cap + "\n" + pdf_txt).strip())
    return texts


# ── 도메인별 엔트리포인트 ─────────────────────────────────────────────
def rebuild_image_lexical() -> dict:
    """image 도메인 vocab + asf_token_sets + sparse 재빌드."""
    cache = Path(PATHS["TRICHEF_IMG_CACHE"])
    ids_path = cache / "img_ids.json"
    if not ids_path.exists():
        return {"skipped": True, "reason": "img_ids.json 없음"}
    ids = json.loads(ids_path.read_text(encoding="utf-8"))["ids"]
    cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    # stem_key_for(i) 우선, 없으면 plain stem fallback (Qwen recaption_all 은 plain stem 사용)
    docs = []
    empty = 0
    for i in ids:
        txt = load_caption(cap_dir, stem_key_for(i))
        if not txt:
            txt = load_caption(cap_dir, Path(i).stem)
        if not txt:
            empty += 1
        docs.append(txt)
    logger.info(f"[lexical_rebuild:image] 캡션 로드: 빈 {empty}/{len(docs)}")

    vocab = auto_vocab.build_vocab(docs, min_df=2, max_df_ratio=0.5, top_k=5000)
    auto_vocab.save_vocab(cache / "auto_vocab.json", vocab)

    sets = asf_filter.build_doc_token_sets(docs, vocab)
    asf_filter.save_token_sets(cache / "asf_token_sets.json", sets)

    mat = _encode_sparse(docs)
    sp.save_npz(cache / "cache_img_sparse.npz", mat)

    logger.info(f"[lexical_rebuild:image] vocab={len(vocab)} "
                f"asf_nonempty={sum(1 for s in sets if s)}/{len(sets)} "
                f"sparse={mat.shape} nnz={mat.nnz}")
    return {"vocab": len(vocab), "sparse": list(mat.shape), "nnz": int(mat.nnz)}


def rebuild_doc_lexical() -> dict:
    """doc_page 도메인 vocab + asf_token_sets + sparse (캡션+PDF원문) 재빌드."""
    cache = Path(PATHS["TRICHEF_DOC_CACHE"])
    ids_path = cache / "doc_page_ids.json"
    if not ids_path.exists():
        return {"skipped": True, "reason": "doc_page_ids.json 없음"}
    ids = json.loads(ids_path.read_text(encoding="utf-8"))["ids"]

    texts = _doc_page_texts(ids)

    vocab = auto_vocab.build_vocab(texts, min_df=2, max_df_ratio=0.4, top_k=25000)
    auto_vocab.save_vocab(cache / "auto_vocab.json", vocab)

    sets = asf_filter.build_doc_token_sets(texts, vocab)
    asf_filter.save_token_sets(cache / "asf_token_sets.json", sets)

    mat = _encode_sparse(texts, max_length=2048)
    sp.save_npz(cache / "cache_doc_page_sparse.npz", mat)

    logger.info(f"[lexical_rebuild:doc_page] vocab={len(vocab)} "
                f"asf_nonempty={sum(1 for s in sets if s)}/{len(sets)} "
                f"sparse={mat.shape} nnz={mat.nnz}")
    return {"vocab": len(vocab), "sparse": list(mat.shape), "nnz": int(mat.nnz)}
