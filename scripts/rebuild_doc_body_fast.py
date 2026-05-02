"""Doc 본문 추출 + BGE-M3 임베딩 — PyMuPDF + multiprocessing + GPU.

기존 rebuild_doc_im_body.py 대비 5~30배 빠름:
  - PyMuPDF (fitz) — pdfplumber 보다 5-10배 빠른 본문 추출
  - multiprocessing 8 worker — CPU 32코어 활용
  - BGE-M3 batch 64 GPU 임베딩

작업:
  1. ids.json 페이지 그룹화 (PDF 단위)
  2. multiprocessing 으로 PDF 별 텍스트 일괄 추출
     - 결과 텍스트는 메모리에 dict 로 보관 (디스크 저장도 가능)
  3. extracted_DB/Doc/page_text/<stem>/p####.txt 도 저장 (ASF vocab 활용)
  4. BGE-M3 batch GPU 임베딩
  5. cache_doc_page_Im_body.npy (34661 × 1024) 저장

사용:
  python scripts/rebuild_doc_body_fast.py
  python scripts/rebuild_doc_body_fast.py --workers 8 --batch-size 64
"""
from __future__ import annotations
import argparse
import io
import json
import multiprocessing as mp
import re
import shutil
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("[rebuild_doc_body_fast] 시작", flush=True)

ROOT = Path(__file__).resolve().parents[1]
DOC_CACHE = ROOT / "Data" / "embedded_DB" / "Doc"
PAGE_TEXT_DIR = ROOT / "Data" / "extracted_DB" / "Doc" / "page_text"
ID_PATTERN = re.compile(r"^page_images/(.+)/p(\d+)\.(?:jpg|png)$")


def parse_id(rid):
    m = ID_PATTERN.match(rid)
    return (m.group(1), int(m.group(2))) if m else (None, None)


def find_pdf_path(stem, registry):
    for k, v in registry.items():
        if isinstance(v, dict) and Path(k).stem == stem:
            ap = v.get("abs")
            if ap and Path(ap).is_file():
                return ap
    if "__" in stem:
        name_part = stem.rsplit("__", 1)[0]
        for k, v in registry.items():
            if isinstance(v, dict) and Path(k).stem == name_part:
                ap = v.get("abs")
                if ap and Path(ap).is_file():
                    return ap
    for k, v in registry.items():
        if not isinstance(v, dict):
            continue
        for a in v.get("abs_aliases") or []:
            ap = Path(a)
            if ap.stem == stem and ap.is_file():
                return str(ap)
    return None


def extract_pdf_pages(args):
    """worker: PDF 1개의 모든 요청 페이지 본문 추출.

    PyMuPDF 결과가 빈 경우 page_text/<stem>/p####.txt (OCR 결과) 에서 fallback.

    Returns: {(stem, page_num): text} 딕셔너리.
    """
    stem, pdf_path, page_nums, save_text_dir = args
    out: dict = {}
    save_dir = Path(save_text_dir) if save_text_dir else None
    try:
        import fitz  # PyMuPDF
    except ImportError:
        fitz = None

    doc = None
    if pdf_path and fitz is not None:
        try:
            doc = fitz.open(pdf_path)
        except Exception:
            doc = None

    n_pages = len(doc) if doc is not None else 0
    for pn in page_nums:
        txt = ""
        # 1차: PyMuPDF 텍스트 레이어
        if doc is not None and 0 < pn <= n_pages:
            try:
                txt = doc[pn - 1].get_text() or ""
            except Exception:
                txt = ""
        # 2차: OCR 결과 fallback (PyMuPDF 가 빈 텍스트 반환 시)
        if not txt.strip() and save_dir is not None:
            ocr_path = save_dir / stem / f"p{pn:04d}.txt"
            if ocr_path.is_file():
                try:
                    txt = ocr_path.read_text(encoding="utf-8")
                except Exception:
                    pass
        out[(stem, pn)] = txt
        # 디스크 저장 — PyMuPDF 결과만 (OCR 은 이미 저장되어 있음)
        if save_dir is not None and txt.strip():
            ocr_path = save_dir / stem / f"p{pn:04d}.txt"
            if not ocr_path.exists():
                ocr_path.parent.mkdir(parents=True, exist_ok=True)
                ocr_path.write_text(txt, encoding="utf-8")

    if doc is not None:
        try:
            doc.close()
        except Exception:
            pass
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--skip-embed", action="store_true",
                        help="텍스트만 추출, BGE-M3 임베딩 X")
    args = parser.parse_args()

    # 1. ids 로드
    ids_data = json.loads((DOC_CACHE / "doc_page_ids.json").read_text(encoding="utf-8"))
    ids = ids_data.get("ids", []) if isinstance(ids_data, dict) else ids_data
    n_total = len(ids)
    print(f"ids: {n_total}", flush=True)

    registry = json.loads((DOC_CACHE / "registry.json").read_text(encoding="utf-8"))
    print(f"registry: {len(registry)}", flush=True)

    # 2. PDF 단위로 그룹화 + 미리 PDF path 매핑
    pdf_groups: dict[str, list[tuple[int, int]]] = {}  # stem → [(idx_in_ids, page_num)]
    miss_pdf = set()
    pdf_path_cache: dict[str, str | None] = {}
    for i, rid in enumerate(ids):
        stem, page_num = parse_id(rid)
        if stem is None:
            continue
        if stem not in pdf_path_cache:
            pdf_path_cache[stem] = find_pdf_path(stem, registry)
            if pdf_path_cache[stem] is None:
                miss_pdf.add(stem)
        pdf_groups.setdefault(stem, []).append((i, page_num))

    print(f"PDF 그룹: {len(pdf_groups)}, PDF 미발견: {len(miss_pdf)}", flush=True)

    # 3. multiprocessing 으로 PDF 단위 텍스트 추출
    PAGE_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = [
        (stem, pdf_path_cache[stem],
         [pn for _, pn in pdf_groups[stem]],
         str(PAGE_TEXT_DIR))
        for stem in pdf_groups
        if pdf_path_cache.get(stem)
    ]
    print(f"추출 작업: {len(tasks)} PDF, workers={args.workers}", flush=True)

    t0 = time.time()
    text_map: dict = {}
    with mp.Pool(processes=args.workers) as pool:
        n_done = 0
        for result in pool.imap_unordered(extract_pdf_pages, tasks, chunksize=4):
            text_map.update(result)
            n_done += 1
            if n_done % 20 == 0:
                elapsed = time.time() - t0
                eta = elapsed / max(n_done, 1) * (len(tasks) - n_done)
                print(f"  PDF {n_done}/{len(tasks)} 처리 elapsed={elapsed:.0f}s eta={eta:.0f}s",
                      flush=True)
    print(f"\n추출 완료 ({time.time() - t0:.0f}s, 페이지 {len(text_map)}개)", flush=True)

    # 4. ids 순서대로 텍스트 정렬 (ids[i] 의 page_num 매칭)
    print("ids 순서 정렬...", flush=True)
    texts: list[str] = [""] * n_total
    n_empty = 0
    for i, rid in enumerate(ids):
        stem, pn = parse_id(rid)
        if stem is None:
            n_empty += 1
            continue
        t = text_map.get((stem, pn), "")
        if not t:
            n_empty += 1
        texts[i] = t
    print(f"  비어있는 페이지: {n_empty}/{n_total}", flush=True)

    if args.skip_embed:
        print("(--skip-embed: 임베딩 미실행)", flush=True)
        return 0

    # 5. BGE-M3 임베딩
    print("\nBGE-M3 GPU 임베딩 시작...", flush=True)
    sys.path.insert(0, str(ROOT / "App" / "backend"))
    from embedders.trichef import bgem3_caption_im as bge
    import numpy as np

    out_emb = np.zeros((n_total, 1024), dtype=np.float32)
    non_empty_idx = [i for i, t in enumerate(texts) if t]
    non_empty_texts = [texts[i] for i in non_empty_idx]
    print(f"  비-empty: {len(non_empty_idx)}, batch={args.batch_size}", flush=True)

    bs = args.batch_size
    t1 = time.time()
    for s in range(0, len(non_empty_texts), bs):
        e = min(s + bs, len(non_empty_texts))
        batch = non_empty_texts[s:e]
        try:
            embs = bge.embed_passage(batch)
        except Exception as ex:
            print(f"    batch {s}-{e} 실패: {ex}", flush=True)
            continue
        for j, idx in enumerate(non_empty_idx[s:e]):
            out_emb[idx] = embs[j]
        if (s // bs) % 50 == 0 and s > 0:
            elapsed = time.time() - t1
            eta = elapsed / max(s, 1) * (len(non_empty_texts) - s)
            print(f"  embed {s}/{len(non_empty_texts)} elapsed={elapsed:.0f}s eta={eta:.0f}s",
                  flush=True)

    print(f"  임베딩 완료 ({time.time() - t1:.0f}s)", flush=True)

    # 정규화
    norms = np.linalg.norm(out_emb, axis=1, keepdims=True)
    out_emb = out_emb / np.maximum(norms, 1e-9)

    # 6. 저장
    npy_path = DOC_CACHE / "cache_doc_page_Im_body.npy"
    if npy_path.exists():
        bak = npy_path.with_suffix(npy_path.suffix + f".bak.{int(time.time())}")
        shutil.copy2(npy_path, bak)
        print(f"  백업: {bak.name}", flush=True)
    np.save(npy_path, out_emb)
    print(f"  저장: {npy_path.name} {out_emb.shape}", flush=True)
    print(f"\n전체 완료 ({time.time() - t0:.0f}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
