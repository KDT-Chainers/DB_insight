"""스캔 PDF 페이지 OCR (EasyOCR GPU) — Doc 본문 보강.

대상: page_text/<stem>/p####.txt 가 없는 (PyMuPDF 본문 추출 실패) 페이지.
GPU EasyOCR 한국어+영어 모델 → page_text/<stem>/p####.txt 저장.

사용:
  python scripts/ocr_doc_pages.py --top-n 10        # 상위 10 PDF (~1500 페이지)
  python scripts/ocr_doc_pages.py --top-n 50        # 상위 50 PDF
  python scripts/ocr_doc_pages.py --max-pages 1500  # 최대 1500 페이지만
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("[ocr_doc_pages] 시작", flush=True)

ROOT = Path(__file__).resolve().parents[1]
DOC_CACHE = ROOT / "Data" / "embedded_DB" / "Doc"
PAGE_TEXT = ROOT / "Data" / "extracted_DB" / "Doc" / "page_text"
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-n", type=int, default=10,
                        help="빈 페이지 가장 많은 상위 N PDF")
    parser.add_argument("--max-pages", type=int, default=1600,
                        help="총 처리 페이지 상한")
    parser.add_argument("--zoom", type=float, default=2.0,
                        help="렌더 zoom (OCR 정확도 향상)")
    parser.add_argument("--min-conf", type=float, default=0.3,
                        help="OCR confidence 임계값 (이하 텍스트 제거)")
    args = parser.parse_args()

    # ids + registry
    ids_data = json.loads((DOC_CACHE / "doc_page_ids.json").read_text(encoding="utf-8"))
    ids = ids_data.get("ids", []) if isinstance(ids_data, dict) else ids_data
    registry = json.loads((DOC_CACHE / "registry.json").read_text(encoding="utf-8"))

    # 빈 페이지 식별 + PDF 별 그룹화
    empty_by_pdf: dict[str, list[int]] = {}
    for rid in ids:
        stem, pn = parse_id(rid)
        if stem is None:
            continue
        txt_path = PAGE_TEXT / stem / f"p{pn:04d}.txt"
        if not txt_path.exists():
            empty_by_pdf.setdefault(stem, []).append(pn)

    # 상위 N PDF 선택
    sorted_pdfs = sorted(empty_by_pdf.items(), key=lambda x: -len(x[1]))
    target_pdfs = sorted_pdfs[:args.top_n]
    total_pages = sum(len(pages) for _, pages in target_pdfs)
    if total_pages > args.max_pages:
        # 페이지 합이 max-pages 넘으면 자름
        budget = args.max_pages
        cut = []
        for stem, pages in target_pdfs:
            if budget <= 0:
                break
            cut.append((stem, pages[:budget]))
            budget -= len(pages[:budget])
        target_pdfs = cut
        total_pages = sum(len(pages) for _, pages in target_pdfs)

    print(f"대상 PDF: {len(target_pdfs)}, 총 페이지: {total_pages}", flush=True)
    for stem, pages in target_pdfs:
        print(f"  {len(pages):>4} pages: {stem[:80]}", flush=True)

    # EasyOCR GPU 로드
    print("\nEasyOCR 모델 로드 중 (ko+en, GPU)...", flush=True)
    import easyocr
    reader = easyocr.Reader(["ko", "en"], gpu=True, verbose=False)
    print("로드 완료", flush=True)

    # PyMuPDF 페이지 렌더링 + OCR
    import fitz
    import numpy as np

    n_done = 0
    n_fail = 0
    total_processed = 0
    t0 = time.time()
    for stem, pages in target_pdfs:
        pdf_path = find_pdf_path(stem, registry)
        if not pdf_path:
            print(f"  PDF 미발견: {stem}", flush=True)
            n_fail += len(pages)
            continue
        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            print(f"  열기 실패: {stem} — {e}", flush=True)
            n_fail += len(pages)
            continue

        out_dir = PAGE_TEXT / stem
        out_dir.mkdir(parents=True, exist_ok=True)
        mat = fitz.Matrix(args.zoom, args.zoom)
        n_pdf_done = 0
        for pn in pages:
            if not (0 < pn <= len(doc)):
                n_fail += 1
                continue
            try:
                page = doc[pn - 1]
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    pix.height, pix.width, pix.n
                )
                # EasyOCR — confidence 필터링
                # detail=1 → [(bbox, text, conf), ...]
                results = reader.readtext(img, detail=1, paragraph=False)
                filtered = [t for (_, t, c) in results if c >= args.min_conf and t.strip()]
                text = "\n".join(filtered)
                if text.strip():
                    (out_dir / f"p{pn:04d}.txt").write_text(text, encoding="utf-8")
                    n_done += 1
                    n_pdf_done += 1
                else:
                    n_fail += 1
                total_processed += 1
            except Exception:
                n_fail += 1
                total_processed += 1

            if total_processed % 50 == 0 and total_processed > 0:
                elapsed = time.time() - t0
                eta = elapsed / total_processed * (total_pages - total_processed)
                print(f"  {total_processed}/{total_pages} done={n_done} fail={n_fail} "
                      f"elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)
        doc.close()
        print(f"  + {stem[:50]}: {n_pdf_done}/{len(pages)} OCR 성공", flush=True)

    print(f"\n전체 완료: done={n_done} fail={n_fail} elapsed={time.time() - t0:.0f}s",
          flush=True)


if __name__ == "__main__":
    main()
