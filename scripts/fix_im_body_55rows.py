"""scripts/fix_im_body_55rows.py — Im_body cache 55행 패치.

_body_texts.json (34,663 texts) + 새 55 페이지 텍스트 추출 → _body_texts.json (34,718)
cache_doc_page_Im_body.npy (34,663 rows) + 55행 임베딩 → cache_doc_page_Im_body.npy (34,718)

Phase 1 (CPU): --extract-only  → _body_texts.json 패치
Phase 2 (GPU): --embed-only    → cache_doc_page_Im_body.npy 패치
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT         = Path(__file__).resolve().parents[1]
DB_DIR       = ROOT / "Data" / "embedded_DB" / "Doc"
RAW_DIR      = ROOT / "Data" / "raw_DB" / "Doc"
IDS_PATH     = DB_DIR / "doc_page_ids.json"
TEXTS_PATH   = DB_DIR / "_body_texts.json"
BODY_NPY     = DB_DIR / "cache_doc_page_Im_body.npy"
IM_NPY       = DB_DIR / "cache_doc_page_Im.npy"

EMPTY_TEXT   = " "

sys.path.insert(0, str(ROOT / "App" / "backend"))


def _parse_id(id_str: str):
    """'page_images/{pdf_stem}/p{NNNN}.jpg' → (pdf_stem, page_idx)."""
    parts = id_str.replace("\\", "/").split("/")
    page_file = parts[-1]
    pdf_stem  = parts[-2]
    page_idx  = int(page_file.lstrip("p").split(".")[0])
    return pdf_stem, page_idx


def _find_pdf(pdf_stem: str) -> Path | None:
    for p in RAW_DIR.rglob(f"{pdf_stem}.pdf"):
        return p
    for p in RAW_DIR.rglob("*.pdf"):
        if p.stem == pdf_stem:
            return p
    return None


def _extract_text(id_str: str) -> str:
    try:
        import pdfplumber
        pdf_stem, page_idx = _parse_id(id_str)
        pdf_path = _find_pdf(pdf_stem)
        if pdf_path is None:
            return EMPTY_TEXT
        with pdfplumber.open(str(pdf_path)) as pdf:
            if page_idx < len(pdf.pages):
                t = pdf.pages[page_idx].extract_text() or ""
                t = " ".join(t.split())
                return t if t.strip() else EMPTY_TEXT
        return EMPTY_TEXT
    except Exception as e:
        print(f"  [extract] {id_str}: {e}", flush=True)
        return EMPTY_TEXT


def phase1_extract():
    import numpy as np

    # Load IDs
    ids_raw = json.loads(IDS_PATH.read_text(encoding="utf-8"))
    ids = ids_raw.get("ids", ids_raw) if isinstance(ids_raw, dict) else ids_raw
    N_new = len(ids)
    print(f"[fix_55] 전체 IDs: {N_new}", flush=True)

    # Load existing texts
    existing = json.loads(TEXTS_PATH.read_text(encoding="utf-8"))
    N_old = len(existing)
    print(f"[fix_55] 기존 텍스트: {N_old}  →  {N_new - N_old}행 추가 필요", flush=True)

    if N_old == N_new:
        print("[fix_55] 이미 정합. 종료.", flush=True)
        return

    if N_old > N_new:
        print(f"[fix_55] 기존({N_old}) > 신규({N_new}) — 뭔가 이상합니다.", flush=True)
        return

    # Extract new pages
    new_texts = []
    new_ids = ids[N_old:]
    print(f"[fix_55] 추가 ID 범위: [{N_old}:{N_new}]", flush=True)
    for i, id_str in enumerate(new_ids):
        t = _extract_text(id_str)
        new_texts.append(t)
        if (i + 1) % 10 == 0 or i == len(new_ids) - 1:
            print(f"  추출 {i+1}/{len(new_ids)}", flush=True)

    # Save merged
    merged = existing + new_texts
    assert len(merged) == N_new, f"merge 실패: {len(merged)} != {N_new}"
    TEXTS_PATH.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    print(f"[fix_55] _body_texts.json 저장 ({N_new}건)", flush=True)


def phase2_embed():
    import numpy as np

    # Load IDs + texts
    ids_raw = json.loads(IDS_PATH.read_text(encoding="utf-8"))
    ids = ids_raw.get("ids", ids_raw) if isinstance(ids_raw, dict) else ids_raw
    N_new = len(ids)

    texts = json.loads(TEXTS_PATH.read_text(encoding="utf-8"))
    assert len(texts) == N_new, f"texts 크기 {len(texts)} != {N_new}"

    # Load existing cache
    existing_npy = np.load(str(BODY_NPY)).astype(np.float32)
    N_old = existing_npy.shape[0]
    D = existing_npy.shape[1]
    print(f"[fix_55] 기존 Im_body: {N_old}×{D}  추가 필요: {N_new - N_old}행", flush=True)

    if N_old == N_new:
        print("[fix_55] Im_body 이미 정합. 종료.", flush=True)
        return

    # Embed new texts only
    new_texts = texts[N_old:]
    print(f"[fix_55] BGE-M3 임베딩 {len(new_texts)}행 …", flush=True)
    from embedders.trichef import bgem3_caption_im as _bge
    batch = 32
    vecs = []
    for i in range(0, len(new_texts), batch):
        chunk = new_texts[i:i+batch]
        emb = _bge.embed_passage(chunk, batch_size=batch)
        vecs.append(emb)
        print(f"  임베딩 {min(i+batch, len(new_texts))}/{len(new_texts)}", flush=True)

    new_emb = np.vstack(vecs).astype(np.float32)
    assert new_emb.shape == (len(new_texts), D), f"shape mismatch: {new_emb.shape}"

    merged = np.vstack([existing_npy, new_emb])
    assert merged.shape == (N_new, D)

    # Backup + save
    bak = BODY_NPY.with_suffix(".npy.bak_fix55")
    import shutil
    shutil.copy2(str(BODY_NPY), str(bak))
    np.save(str(BODY_NPY), merged)
    print(f"[fix_55] cache_doc_page_Im_body.npy 저장 {merged.shape}  (백업→{bak.name})", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--extract-only", action="store_true")
    parser.add_argument("--embed-only", action="store_true")
    args = parser.parse_args()

    if args.embed_only:
        phase2_embed()
    else:
        phase1_extract()
        if not args.extract_only:
            phase2_embed()
