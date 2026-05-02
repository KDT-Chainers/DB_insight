"""page_text 누락 페이지를 PyMuPDF 텍스트 레이어로 재시도.

배경:
  Data/extracted_DB/Doc/page_text/<stem>/p####.txt 가 없는 페이지가 1,064개 (443 docs).
  대부분은 (a) 텍스트 레이어가 있지만 추출 안 됨 / (b) 스캔 PDF (텍스트 레이어 X) — OCR 필요.

전략:
  1. PyMuPDF (fitz) 로 텍스트 레이어 재시도 (CPU only)
  2. 텍스트 추출 성공 시 page_text/<stem>/p####.txt 저장
  3. 추출 실패 시 OCR 후보 목록 (logs/ocr_pending.json) 에 기록

사용:
  python scripts/fill_missing_page_text.py
  python scripts/fill_missing_page_text.py --workers 8
"""
from __future__ import annotations
import argparse
import json
import multiprocessing as mp
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DOC_CACHE = ROOT / "Data" / "embedded_DB" / "Doc"
PAGE_TEXT_DIR = ROOT / "Data" / "extracted_DB" / "Doc" / "page_text"
LOGS = ROOT / "logs"
ID_PATTERN = re.compile(r"^page_images/(.+)/p(\d+)\.(?:jpg|png)$")


def parse_id(rid):
    m = ID_PATTERN.match(rid)
    return (m.group(1), int(m.group(2))) if m else (None, None)


def find_pdf_path(stem, registry):
    # 신포맷
    for k, v in registry.items():
        if isinstance(v, dict) and Path(k).stem == stem:
            ap = v.get("abs")
            if ap and Path(ap).is_file():
                return ap
    # 구포맷 (hash 제거)
    if "__" in stem:
        np_part = stem.rsplit("__", 1)[0]
        for k, v in registry.items():
            if isinstance(v, dict) and Path(k).stem == np_part:
                ap = v.get("abs")
                if ap and Path(ap).is_file():
                    return ap
    # alias
    for k, v in registry.items():
        if not isinstance(v, dict):
            continue
        for a in v.get("abs_aliases") or []:
            if Path(a).stem == stem and Path(a).is_file():
                return a
    return None


def process_pdf(args):
    """worker — PDF 1개의 모든 누락 페이지 텍스트 추출.

    Returns: {(stem, pn): text} 누락 페이지의 결과만.
    """
    stem, pdf_path, page_nums = args
    if not pdf_path or not Path(pdf_path).is_file():
        return {(stem, pn): None for pn in page_nums}
    try:
        import fitz
    except ImportError:
        return {(stem, pn): None for pn in page_nums}

    out: dict = {}
    try:
        with fitz.open(pdf_path) as d:
            n_pages = len(d)
            for pn in page_nums:
                if 0 <= pn < n_pages:
                    try:
                        text = d[pn].get_text("text") or ""
                        out[(stem, pn)] = text.strip()
                    except Exception:
                        out[(stem, pn)] = None
                else:
                    out[(stem, pn)] = None
    except Exception:
        for pn in page_nums:
            out[(stem, pn)] = None
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    print("[fill_missing_page_text] 시작", flush=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    ids = json.loads((DOC_CACHE / "doc_page_ids.json").read_text(encoding="utf-8"))
    ids_list = ids.get("ids", []) if isinstance(ids, dict) else ids
    registry = json.loads((DOC_CACHE / "registry.json").read_text(encoding="utf-8"))

    # 누락 페이지 목록
    missing_groups: dict[str, list[int]] = {}
    pdf_path_cache: dict[str, str | None] = {}
    for rid in ids_list:
        stem, pn = parse_id(rid)
        if stem is None:
            continue
        pt = PAGE_TEXT_DIR / stem / f"p{pn:04d}.txt"
        if pt.is_file():
            continue
        if stem not in pdf_path_cache:
            pdf_path_cache[stem] = find_pdf_path(stem, registry)
        missing_groups.setdefault(stem, []).append(pn)

    n_missing = sum(len(v) for v in missing_groups.values())
    print(f"  누락 페이지: {n_missing}건 / {len(missing_groups)} docs", flush=True)
    miss_pdf = sum(1 for v in pdf_path_cache.values() if v is None)
    print(f"  PDF 미발견: {miss_pdf} stems", flush=True)

    tasks = [
        (stem, pdf_path_cache[stem], page_nums)
        for stem, page_nums in missing_groups.items()
        if pdf_path_cache.get(stem)
    ]
    print(f"  추출 작업: {len(tasks)} PDFs, workers={args.workers}", flush=True)

    t0 = time.time()
    n_filled = 0
    n_still_empty = 0
    ocr_pending: list[dict] = []

    with mp.Pool(processes=args.workers) as pool:
        for result in pool.imap_unordered(process_pdf, tasks, chunksize=4):
            for (stem, pn), text in result.items():
                if text:
                    out_dir = PAGE_TEXT_DIR / stem
                    out_dir.mkdir(parents=True, exist_ok=True)
                    (out_dir / f"p{pn:04d}.txt").write_text(text, encoding="utf-8")
                    n_filled += 1
                else:
                    n_still_empty += 1
                    ocr_pending.append({"stem": stem, "page": pn,
                                        "rid": f"page_images/{stem}/p{pn:04d}.jpg"})

    # PDF 미발견 페이지도 OCR 대상에 추가
    for stem, pns in missing_groups.items():
        if pdf_path_cache.get(stem) is None:
            for pn in pns:
                ocr_pending.append({"stem": stem, "page": pn,
                                    "rid": f"page_images/{stem}/p{pn:04d}.jpg",
                                    "reason": "pdf_not_found"})

    elapsed = time.time() - t0
    print(f"\n  PyMuPDF 채운 페이지: {n_filled}", flush=True)
    print(f"  여전히 빈 페이지 (OCR 필요): {n_still_empty + miss_pdf}", flush=True)
    print(f"  소요: {elapsed:.0f}s", flush=True)

    LOGS.mkdir(parents=True, exist_ok=True)
    pending_path = LOGS / "ocr_pending.json"
    pending_path.write_text(
        json.dumps({"count": len(ocr_pending), "items": ocr_pending},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  OCR 대상 목록: {pending_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
