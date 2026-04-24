"""build_doc_body_im.py — PDF 본문 텍스트 추출 → BGE-M3 Im_body 캐시 생성.

기존 cache_doc_page_Im.npy 는 Qwen 이미지 캡션 기반 (시각 설명).
이 스크립트는 pdfplumber 로 각 페이지 텍스트를 직접 추출 → BGE-M3 임베딩하여
cache_doc_page_Im_body.npy 를 생성한다.

unified_engine.py 의 score fusion:
  Im_fused = alpha * Im_caption + (1-alpha) * Im_body
  default alpha = 0.35

2단계 실행 (GPU 독립적 단계 분리):
  # 1단계: CPU만 사용 — GPU 작업과 병렬 실행 가능
  python MR_TriCHEF/scripts/build_doc_body_im.py --extract-only

  # 2단계: GPU(BGE-M3) 임베딩 — GPU 여유 시 실행
  python MR_TriCHEF/scripts/build_doc_body_im.py --embed-only

  # 전체 한번에:
  python MR_TriCHEF/scripts/build_doc_body_im.py --batch 32 --resume
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "MR_TriCHEF"))

DOC_CACHE_DIR = _root / "Data" / "embedded_DB" / "Doc"
DOC_RAW_DIR   = _root / "Data" / "raw_DB" / "Doc"
OUT_PATH      = DOC_CACHE_DIR / "cache_doc_page_Im_body.npy"
PROG_PATH     = DOC_CACHE_DIR / "_body_progress.json"

EMPTY_TEXT = " "   # BGE-M3 에 빈 문자열 대신 공백 전달


# ── PDF 텍스트 추출 ────────────────────────────────────────────────────────────
def _extract_page_texts(pdf_path: Path, n_pages: int) -> list[str]:
    """pdfplumber 로 n_pages 개 페이지 텍스트 추출. 실패 시 빈 문자열."""
    try:
        import pdfplumber
        texts: list[str] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for i in range(n_pages):
                if i < len(pdf.pages):
                    try:
                        t = pdf.pages[i].extract_text() or ""
                        # 줄바꿈/공백 정규화
                        t = " ".join(t.split())
                        texts.append(t if t.strip() else EMPTY_TEXT)
                    except Exception:
                        texts.append(EMPTY_TEXT)
                else:
                    texts.append(EMPTY_TEXT)
        return texts
    except Exception as e:
        print(f"  [pdfplumber] {pdf_path.name}: {e}")
        return [EMPTY_TEXT] * n_pages


# ── IDs → (pdf_stem, page_idx) 파싱 ──────────────────────────────────────────
def _parse_id(id_str: str) -> tuple[str, int]:
    """'page_images/{pdf_stem}/p{NNNN}.jpg' → (pdf_stem, page_idx)."""
    parts = id_str.replace("\\", "/").split("/")
    # parts = ['page_images', '{pdf_stem}', 'p0000.jpg']  (stem may have spaces)
    # stem 이 여러 부분일 수 있으므로 -1 이 파일명, -2 가 stem
    page_file = parts[-1]      # p0000.jpg
    pdf_stem  = parts[-2]      # pdf 파일명(확장자 제외)
    page_idx  = int(page_file.lstrip("p").split(".")[0])
    return pdf_stem, page_idx


def _find_pdf(pdf_stem: str) -> Path | None:
    """raw_DB/Doc 에서 stem 이 일치하는 PDF 탐색 (rglob)."""
    # 정확 일치 우선
    for p in DOC_RAW_DIR.rglob(f"{pdf_stem}.pdf"):
        return p
    # 공백/특수문자 이슈 대비 — stem 비교
    for p in DOC_RAW_DIR.rglob("*.pdf"):
        if p.stem == pdf_stem:
            return p
    return None


# ── 메인 ──────────────────────────────────────────────────────────────────────
TEXT_CACHE_PATH = DOC_CACHE_DIR / "_body_texts.json"   # 텍스트 추출 중간 저장


def phase1_extract(ids: list[str]) -> list[str]:
    """1단계: pdfplumber 텍스트 추출 (CPU전용, GPU 작업과 병렬 실행 가능).

    결과를 _body_texts.json 에 저장하고 texts 리스트 반환.
    """
    N = len(ids)
    print(f"[doc_body:1단계] 텍스트 추출 시작 — {N:,} 페이지 / {DOC_RAW_DIR}")

    pdf_groups: dict[str, list[int]] = {}
    for gi, id_str in enumerate(ids):
        pdf_stem, _ = _parse_id(id_str)
        pdf_groups.setdefault(pdf_stem, []).append(gi)

    text_buf: dict[int, str] = {}
    pdf_total = len(pdf_groups)

    for pi, (pdf_stem, g_idxs) in enumerate(pdf_groups.items(), 1):
        pdf_path = _find_pdf(pdf_stem)
        if pdf_path is None:
            for gi in g_idxs:
                text_buf[gi] = EMPTY_TEXT
            if pi % 50 == 0 or pi == pdf_total:
                print(f"  [{pi}/{pdf_total}] (PDF 없음) {pdf_stem[:50]}")
        else:
            sorted_pairs = sorted(zip(g_idxs, [_parse_id(ids[gi])[1] for gi in g_idxs]),
                                   key=lambda x: x[1])
            max_page = max(p for _, p in sorted_pairs) + 1
            page_texts = _extract_page_texts(pdf_path, max_page)
            for gi, pg_idx in sorted_pairs:
                text_buf[gi] = page_texts[pg_idx] if pg_idx < len(page_texts) else EMPTY_TEXT
            if pi % 50 == 0 or pi == pdf_total:
                print(f"  [{pi}/{pdf_total}] {pdf_path.name[:55]}")

    texts = [text_buf[gi] for gi in range(N)]

    # 중간 저장 (embed 단계에서 재사용)
    TEXT_CACHE_PATH.write_text(
        json.dumps(texts, ensure_ascii=False), encoding="utf-8"
    )
    non_empty = sum(1 for t in texts if t.strip() and t != EMPTY_TEXT)
    print(f"\n[doc_body:1단계] 완료 — 비어있지 않은 페이지: {non_empty:,}/{N:,} "
          f"({non_empty/N*100:.1f}%)")
    print(f"  저장: {TEXT_CACHE_PATH}")
    return texts


def phase2_embed(texts: list[str], batch: int = 64) -> np.ndarray:
    """2단계: BGE-M3 임베딩 (GPU). phase1 완료 후 실행."""
    N = len(texts)
    print(f"[doc_body:2단계] BGE-M3 임베딩 — {N:,} 텍스트  batch={batch}")
    from pipeline.text import BGEM3Encoder
    bge = BGEM3Encoder()

    vecs: list[np.ndarray] = []
    for i in range(0, N, batch):
        emb = bge.embed(texts[i:i + batch], batch=batch)
        vecs.append(emb)
        done = i + len(texts[i:i + batch])
        if (i // batch) % 50 == 0:
            print(f"  임베딩 {done:,}/{N:,} ({done/N*100:.1f}%)")

    bge.unload(); del bge
    result = np.vstack(vecs).astype(np.float32)
    print(f"[doc_body:2단계] 완료 — shape: {result.shape}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=64,
                        help="BGE-M3 배치 크기 (VRAM 절약: 32~128)")
    parser.add_argument("--resume", action="store_true",
                        help="이미 처리된 페이지 skip")
    parser.add_argument("--extract-only", action="store_true",
                        help="1단계만 실행: pdfplumber 텍스트 추출 (CPU, GPU 병렬 실행 가능)")
    parser.add_argument("--embed-only", action="store_true",
                        help="2단계만 실행: BGE-M3 임베딩 (_body_texts.json 필요)")
    args = parser.parse_args()

    # IDs 로드
    ids_path = DOC_CACHE_DIR / "doc_page_ids.json"
    ids_raw  = json.loads(ids_path.read_text(encoding="utf-8"))
    ids      = ids_raw.get("ids", ids_raw) if isinstance(ids_raw, dict) else ids_raw
    N        = len(ids)
    print(f"[doc_body] 총 페이지: {N:,}")

    # ── 1단계: 텍스트 추출 ───────────────────────────────────────
    if not args.embed_only:
        if args.resume and TEXT_CACHE_PATH.exists():
            existing = json.loads(TEXT_CACHE_PATH.read_text(encoding="utf-8"))
            if len(existing) == N:
                print(f"  [resume] 기존 텍스트 캐시 사용 ({N:,}개)")
                texts = existing
            else:
                print(f"  [resume] 텍스트 캐시 크기 불일치 ({len(existing)} vs {N}) → 재추출")
                texts = phase1_extract(ids)
        else:
            texts = phase1_extract(ids)
    else:
        if not TEXT_CACHE_PATH.exists():
            print(f"[오류] {TEXT_CACHE_PATH} 없음 — 먼저 --extract-only 실행")
            return
        texts = json.loads(TEXT_CACHE_PATH.read_text(encoding="utf-8"))
        if len(texts) != N:
            print(f"[오류] 텍스트 캐시 크기 {len(texts)} != IDs {N}")
            return
        print(f"  [embed-only] 텍스트 캐시 로드 ({N:,}개)")

    if args.extract_only:
        print("\n[doc_body] --extract-only 완료. 다음 단계:")
        print("  python MR_TriCHEF/scripts/build_doc_body_im.py --embed-only")
        return

    # ── 2단계: 임베딩 ────────────────────────────────────────────
    final = phase2_embed(texts, batch=args.batch)

    # 저장
    np.save(OUT_PATH, final)
    PROG_PATH.write_text(json.dumps({"done": N}, ensure_ascii=False), encoding="utf-8")
    print(f"\n[doc_body] 저장 완료: {OUT_PATH}")
    print(f"  shape: {final.shape}  ({final.nbytes / 1024**2:.1f} MB)")
    print(f"  unified_engine.py Im_body fusion (alpha=0.35) 즉시 활성화됩니다.")
    print(f"  다음 단계: App/backend 서버 재시작")


if __name__ == "__main__":
    sys.exit(main())
