"""Doc 페이지 본문 텍스트만 빠르게 추출 (임베딩 X) → ASF Doc vocab 재구축용.

rebuild_doc_im_body.py 와 다른 점:
  - 임베딩 단계 없음 (시간 단축)
  - extracted_DB/Doc/page_text/<stem>/p####.txt 에 텍스트 저장
  - rebuild_asf_vocab.py 가 이 파일들을 자동 활용 (이미 코드에 있음)

출력: extracted_DB/Doc/page_text/<doc_stem>/p####.txt
"""
from __future__ import annotations
import sys
import time
import re
import json
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("[extract_doc_page_text] 시작", flush=True)

ROOT = Path(__file__).resolve().parents[1]
DOC_CACHE = ROOT / "Data" / "embedded_DB" / "Doc"
PAGE_TEXT_DIR = ROOT / "Data" / "extracted_DB" / "Doc" / "page_text"

ID_PATTERN = re.compile(r"^page_images/(.+)/p(\d+)\.(?:jpg|png)$")


def parse_id(rid):
    m = ID_PATTERN.match(rid)
    if not m:
        return None, None
    return m.group(1), int(m.group(2))


def find_pdf_path(stem, registry):
    for k, v in registry.items():
        if not isinstance(v, dict):
            continue
        if Path(k).stem == stem:
            ap = v.get("abs")
            if ap and Path(ap).is_file():
                return Path(ap)
    if "__" in stem:
        name_part = stem.rsplit("__", 1)[0]
        for k, v in registry.items():
            if isinstance(v, dict) and Path(k).stem == name_part:
                ap = v.get("abs")
                if ap and Path(ap).is_file():
                    return Path(ap)
    for k, v in registry.items():
        if not isinstance(v, dict):
            continue
        for a in v.get("abs_aliases") or []:
            ap = Path(a)
            if ap.stem == stem and ap.is_file():
                return ap
    return None


def main():
    ids_data = json.loads((DOC_CACHE / "doc_page_ids.json").read_text(encoding="utf-8"))
    ids = ids_data.get("ids", []) if isinstance(ids_data, dict) else ids_data
    n_total = len(ids)
    print(f"ids: {n_total}", flush=True)

    registry = json.loads((DOC_CACHE / "registry.json").read_text(encoding="utf-8"))

    PAGE_TEXT_DIR.mkdir(parents=True, exist_ok=True)

    import pdfplumber

    pdf_cache = {}
    pdf_obj_cache = {}     # stem → opened pdfplumber object (페이지 빠른 접근)
    n_done = 0
    n_fail = 0
    n_skip = 0
    t0 = time.time()

    # 같은 PDF 의 여러 페이지를 연속 처리하도록 정렬
    sorted_indices = sorted(range(n_total), key=lambda i: ids[i])

    last_stem = None
    pdf_obj = None
    for j, i in enumerate(sorted_indices):
        rid = ids[i]
        stem, page_num = parse_id(rid)
        if stem is None:
            n_fail += 1
            continue

        # 출력 경로
        out_dir = PAGE_TEXT_DIR / stem
        out_path = out_dir / f"p{page_num:04d}.txt"
        if out_path.exists():
            n_skip += 1
            continue

        if stem not in pdf_cache:
            pdf_cache[stem] = find_pdf_path(stem, registry)
        pdf_path = pdf_cache[stem]
        if pdf_path is None:
            n_fail += 1
            continue

        # PDF 객체 재사용 (같은 stem 의 페이지는 연속 처리)
        if last_stem != stem:
            if pdf_obj is not None:
                try:
                    pdf_obj.close()
                except Exception:
                    pass
            try:
                pdf_obj = pdfplumber.open(str(pdf_path))
            except Exception as e:
                pdf_obj = None
                n_fail += 1
                last_stem = stem
                continue
            last_stem = stem

        if pdf_obj is None:
            n_fail += 1
            continue

        try:
            if 0 < page_num <= len(pdf_obj.pages):
                t = pdf_obj.pages[page_num - 1].extract_text() or ""
            else:
                t = ""
        except Exception:
            t = ""

        if t.strip():
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(t, encoding="utf-8")
            n_done += 1
        else:
            n_fail += 1

        if j % 500 == 0:
            elapsed = time.time() - t0
            eta = elapsed / max(j, 1) * (n_total - j) if j else 0
            print(f"  {j}/{n_total} done={n_done} fail={n_fail} skip={n_skip} "
                  f"elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)

    if pdf_obj is not None:
        try:
            pdf_obj.close()
        except Exception:
            pass

    print(f"\n완료: done={n_done} fail={n_fail} skip={n_skip} elapsed={time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
