"""Doc Im_body 캐시 재구축 — 누락 491 페이지 본문 임베딩.

작동:
  1. ids.json (34661 페이지 ID) 와 cache_doc_page_Im_body.npy (34170 행) 정렬 검사
  2. 정렬 미스매치면 ids 순서대로 전체 재구축, 일치하면 누락 부분만 추가
  3. PDF 페이지 본문 추출 (pdfplumber) → BGE-M3 임베딩 → .npy 저장
  4. 추출 실패 페이지는 zero-vector 1024d 패딩

ids 형식: "page_images/<doc_stem>/p####.jpg"
  → doc_stem 으로 registry 에서 PDF 절대경로 찾기
  → page 번호 (p#### → 1-indexed) 로 pdfplumber 추출

사용:
  python scripts/rebuild_doc_im_body.py            # 전체 재구축
  python scripts/rebuild_doc_im_body.py --dry-run  # 누락 페이지만 보고
"""
from __future__ import annotations
import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

# stdout 인코딩 — TextIOWrapper 재할당 대신 reconfigure 사용 (background redirect 호환)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("[rebuild_doc_im_body] 스크립트 시작", flush=True)

ROOT = Path(__file__).resolve().parents[1]
DOC_CACHE = ROOT / "Data" / "embedded_DB" / "Doc"
IDS_PATH  = DOC_CACHE / "doc_page_ids.json"
IM_BODY   = DOC_CACHE / "cache_doc_page_Im_body.npy"
REG_PATH  = DOC_CACHE / "registry.json"

ID_PATTERN = re.compile(r"^page_images/(.+)/p(\d+)\.(?:jpg|png)$")


def parse_id(rid: str):
    m = ID_PATTERN.match(rid)
    if not m:
        return None, None
    stem, page_str = m.group(1), m.group(2)
    return stem, int(page_str)  # p0001 → 1


def find_pdf_path(stem: str, registry: dict) -> Path | None:
    """registry 에서 stem 에 매칭되는 PDF 의 abs 경로 찾기.

    registry key 형식: "<sub>/<file>.pdf"
    stem 매칭: registry key 의 basename(stem) 또는 stem_key_for() 결과
    """
    # 1. stem 이 registry key 의 basename(extension 제외) 와 일치
    for k, v in registry.items():
        if not isinstance(v, dict):
            continue
        bn = Path(k).stem
        if bn == stem:
            ap = v.get("abs")
            if ap and Path(ap).is_file():
                return Path(ap)
    # 2. stem 형식 "name__hash" → name 부분 매칭
    if "__" in stem:
        name_part = stem.rsplit("__", 1)[0]
        for k, v in registry.items():
            if not isinstance(v, dict):
                continue
            bn = Path(k).stem
            if bn == name_part:
                ap = v.get("abs")
                if ap and Path(ap).is_file():
                    return Path(ap)
    # 3. abs_aliases 도 확인
    for k, v in registry.items():
        if not isinstance(v, dict):
            continue
        for a in v.get("abs_aliases") or []:
            ap = Path(a)
            if ap.stem == stem and ap.is_file():
                return ap
    return None


def extract_page_text(pdf_path: Path, page_num: int) -> str:
    """pdfplumber 로 1-indexed 페이지 본문 추출. 실패 시 빈 문자열."""
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            if 0 < page_num <= len(pdf.pages):
                t = pdf.pages[page_num - 1].extract_text() or ""
                return t.strip()
    except Exception:
        pass
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="누락 페이지 식별만, 임베딩 재실행 X")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    if not IDS_PATH.exists():
        print(f"[ERROR] {IDS_PATH} 없음")
        return 2

    ids_data = json.loads(IDS_PATH.read_text(encoding="utf-8"))
    ids = ids_data.get("ids", []) if isinstance(ids_data, dict) else ids_data
    n_total = len(ids)
    print(f"ids.json 페이지 수: {n_total}")

    registry = json.loads(REG_PATH.read_text(encoding="utf-8")) if REG_PATH.exists() else {}
    print(f"registry entries: {len(registry)}")

    # 본문 임베딩 캐시 상태
    import numpy as np
    if IM_BODY.exists():
        arr = np.load(IM_BODY, mmap_mode="r")
        n_existing = arr.shape[0]
        print(f"기존 cache_doc_page_Im_body.npy: {n_existing} 행")
    else:
        n_existing = 0
        print("기존 cache_doc_page_Im_body.npy: 없음")

    # ids 순서대로 본문 추출 + 임베딩 — 전체 재구축이 안전
    # (기존 cache 의 0..N 행과 ids[0..N] 정렬 보장이 없음)
    print("\n페이지별 본문 추출 시작 (ids 순서대로)...")
    texts: list[str] = []
    fail_count = 0
    pdf_cache: dict[str, Path | None] = {}
    miss_pdfs: set[str] = set()

    for i, rid in enumerate(ids):
        if i % 500 == 0:
            print(f"  진행: {i}/{n_total}  추출실패 {fail_count}")
        stem, page_num = parse_id(rid)
        if stem is None:
            texts.append("")
            fail_count += 1
            continue
        if stem not in pdf_cache:
            pdf_cache[stem] = find_pdf_path(stem, registry)
            if pdf_cache[stem] is None:
                miss_pdfs.add(stem)
        pdf_path = pdf_cache[stem]
        if pdf_path is None:
            texts.append("")
            fail_count += 1
            continue
        t = extract_page_text(pdf_path, page_num)
        if not t:
            fail_count += 1
        texts.append(t)

    n_empty = sum(1 for t in texts if not t)
    print(f"\n추출 결과: 성공 {n_total - n_empty}, 실패 {n_empty}")
    if miss_pdfs:
        print(f"  PDF 미발견 stem: {len(miss_pdfs)}건")
        for s in list(miss_pdfs)[:5]:
            print(f"    - {s}")

    if args.dry_run:
        print("\n(dry-run: 임베딩 미실행)")
        return 0

    # BGE-M3 임베딩
    print(f"\nBGE-M3 임베딩 (batch={args.batch_size})...")
    sys.path.insert(0, str(ROOT / "App" / "backend"))
    from embedders.trichef import bgem3_caption_im as bge

    # 빈 문자열은 placeholder 로 한 번 임베딩 후 zero-vector 로 대체
    out = np.zeros((n_total, 1024), dtype=np.float32)
    non_empty_idx = [i for i, t in enumerate(texts) if t]
    non_empty_texts = [texts[i] for i in non_empty_idx]
    print(f"  비-empty: {len(non_empty_idx)}개")

    for s in range(0, len(non_empty_texts), args.batch_size):
        e = min(s + args.batch_size, len(non_empty_texts))
        batch_texts = non_empty_texts[s:e]
        embs = bge.embed_passage(batch_texts)  # (B, 1024)
        for j, idx in enumerate(non_empty_idx[s:e]):
            out[idx] = embs[j]
        if s % (args.batch_size * 50) == 0:
            print(f"  임베딩 진행: {s}/{len(non_empty_texts)}")

    # 정규화
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    out = out / np.maximum(norms, 1e-9)

    # 백업 + 저장
    if IM_BODY.exists():
        bak = IM_BODY.with_suffix(IM_BODY.suffix + f".bak.{int(time.time())}")
        shutil.copy2(IM_BODY, bak)
        print(f"  백업: {bak.name}")
    np.save(IM_BODY, out)
    print(f"  저장 완료: {IM_BODY.name} ({out.shape})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
