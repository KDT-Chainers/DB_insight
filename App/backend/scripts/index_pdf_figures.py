"""[P4] PDF 내부 figure(도표/사진/그래프) → Img 도메인 임베딩 + 인덱싱.

배경:
  현재 doc 도메인은 페이지 전체를 1장으로 렌더링해 시각 임베딩(Re/Z) 함.
  그러나 페이지 안의 개별 도표·그래프·다이어그램은 별도 검색 단위가 아니라
  페이지 평균 벡터에 묻혀버림 → "보이저호 사진 그림" 같은 시각 쿼리에서
  해당 figure 가 들어있는 페이지가 직접 매칭되지 않을 수 있음.

전략:
  1) raw_DB/Doc/**/*.pdf 순회
  2) PyMuPDF 로 페이지별 embedded image 추출 (filter: ≥100px, aspect ≤12, SHA dedup)
  3) 추출된 figure → Img 도메인 임베딩 파이프라인 (SigLIP2 + BGE-M3 캡션 + DINOv2)
  4) Img 캐시에 doc_figures/<doc_stem>/p<page>_f<idx>_<sha8>.<ext> 키로 추가
  5) Img registry 에 abs_aliases 로 원본 PDF 경로 + 페이지 인덱스 메타 부착
     → 검색 결과에서 "<문서> N페이지의 도표" 표시 가능

기존 인덱스 보존: Img 도메인의 standalone 이미지(staged/...) 와 공존.
   key prefix 로 구분: staged/* (일반 사진) vs doc_figures/* (PDF 추출 도표).

스케일:
  스캔 결과 64,424개 figure 임베딩 후보 (≥100px). dedup 후 추정 20~40K.
  embed_image_file ~5-10s/건 → 총 2~10시간 GPU 소요. 야간 실행 권장.

사용:
  python App/backend/scripts/index_pdf_figures.py --extract-only     # 추출만
  python App/backend/scripts/index_pdf_figures.py --limit-pdf 3      # 3개 PDF만
  python App/backend/scripts/index_pdf_figures.py --resume           # 중단 후 재개
  python App/backend/scripts/index_pdf_figures.py                    # 전체
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# 경로 설정
_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "App" / "backend"))

from config import PATHS  # noqa: E402
from embedders.trichef.pdf_figure_extract import (  # noqa: E402
    extract_figures, iter_pdf_files_in_doc_domain,
)

EXTRACT_ROOT = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "figures"
RAW_DOC = Path(PATHS["RAW_DB"]) / "Doc"
IMG_CACHE = Path(PATHS["TRICHEF_IMG_CACHE"])
PROGRESS_FILE = EXTRACT_ROOT / "_progress.json"


def _load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_progress(prog: dict):
    EXTRACT_ROOT.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(
        json.dumps(prog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def phase1_extract(limit_pdf: int = 0, resume: bool = False) -> list[dict]:
    """Phase 1: 모든 PDF 에서 figure 추출 (디스크 저장).

    Returns:
        [{rel_key, abs_path, src_pdf, page_idx, width, height}, ...]
    """
    progress = _load_progress() if resume else {}
    extracted_log = progress.get("extracted", {})  # {src_pdf: [rel_keys]}

    EXTRACT_ROOT.mkdir(parents=True, exist_ok=True)
    pdfs = list(iter_pdf_files_in_doc_domain(RAW_DOC))
    pdfs.sort()
    if limit_pdf > 0:
        pdfs = pdfs[:limit_pdf]
    print(f"=== Phase 1: PDF figure 추출 ===")
    print(f"  대상 PDF: {len(pdfs)}건  (limit-pdf={limit_pdf}, resume={resume})")

    all_figs: list[dict] = []
    t0 = time.time()
    for i, pdf in enumerate(pdfs, 1):
        pdf_key = str(pdf.resolve())
        if pdf_key in extracted_log:
            # 이미 추출된 PDF — 로그된 rel_keys 만 결과에 포함
            for rk in extracted_log[pdf_key]:
                all_figs.append({"rel_key": rk, "src_pdf": pdf_key})
            continue
        try:
            figs = extract_figures(
                pdf, EXTRACT_ROOT,
                min_side=100, max_aspect=12.0,
                skip_duplicates=True,
            )
            extracted_log[pdf_key] = [f.rel_key for f in figs]
            for f in figs:
                all_figs.append({
                    "rel_key": f.rel_key,
                    "src_pdf": pdf_key,
                    "page_idx": f.page_idx,
                    "fig_idx": f.fig_idx,
                    "out_path": str(f.out_path),
                    "width": f.width,
                    "height": f.height,
                    "ext": f.ext,
                    "sha8": f.sha8,
                })
            elapsed = time.time() - t0
            avg = elapsed / i
            eta = avg * (len(pdfs) - i) / 60
            print(f"  [{i:>4d}/{len(pdfs)}] {pdf.name[:60]:<62s} "
                  f"figs={len(figs):>3d}  avg={avg:.1f}s ETA={eta:.0f}m")
            # 10건마다 진행률 저장
            if i % 10 == 0:
                progress["extracted"] = extracted_log
                _save_progress(progress)
        except Exception as e:
            print(f"  [{i:>4d}] FAIL {pdf.name}: {type(e).__name__}: {e}")

    progress["extracted"] = extracted_log
    _save_progress(progress)
    print(f"\n  Phase 1 완료: 추출 figure 총 {len(all_figs)}개 ({(time.time()-t0):.0f}초)")
    return all_figs


def phase2_embed(figs_meta: list[dict], resume: bool = False,
                 min_side: int = 0, max_per_pdf: int = 0,
                 limit: int = 0):
    """Phase 2: 추출된 figure 들을 Img 도메인에 임베딩 + 등록.

    embed_image_file 을 doc_figures 키 prefix 로 호출.

    Args:
        min_side: max(W,H) < min_side 인 figure 제외 (0=무시)
        max_per_pdf: 한 PDF 당 최대 N개만 (랜덤 선별, 0=무시)
        limit: 전체 처리 상한 (0=무시)
    """
    if not figs_meta:
        print("=== Phase 2: 임베딩 대상 없음 ===")
        return

    # 필터링
    n0 = len(figs_meta)
    if min_side > 0:
        figs_meta = [fm for fm in figs_meta
                     if max(fm.get("width", 0), fm.get("height", 0)) >= min_side]
        print(f"  min-side={min_side} 필터: {n0} → {len(figs_meta)}")
    if max_per_pdf > 0:
        from collections import defaultdict
        by_pdf = defaultdict(list)
        for fm in figs_meta:
            by_pdf[fm.get("src_pdf", "?")].append(fm)
        filtered = []
        for k, lst in by_pdf.items():
            # 크기 순으로 정렬 후 상위 N개 (큰 figure 우선)
            lst.sort(key=lambda x: -(max(x.get("width", 0), x.get("height", 0))))
            filtered.extend(lst[:max_per_pdf])
        before = len(figs_meta)
        figs_meta = filtered
        print(f"  max-per-pdf={max_per_pdf} 필터: {before} → {len(figs_meta)}")
    if limit > 0 and len(figs_meta) > limit:
        figs_meta = figs_meta[:limit]
        print(f"  limit={limit}: → {len(figs_meta)}")

    print(f"=== Phase 2: figure 임베딩 ({len(figs_meta)}건) ===")
    print("  주의: 이 단계는 GPU 사용 (SigLIP2/BGE-M3/DINOv2 + Qwen2-VL 캡션)")
    print(f"        예상 시간: ~3-5s/건 → 총 {len(figs_meta)*4/3600:.1f}시간")
    print()

    # 진행률 로드
    progress = _load_progress()
    done_keys = set(progress.get("embedded", []))
    print(f"  이미 임베딩된: {len(done_keys)}건 (resume 시 skip)")

    from embedders.trichef.incremental_runner import embed_image_file

    t0 = time.time()
    done = err = skip = 0
    for i, fm in enumerate(figs_meta, 1):
        rel_key = fm.get("rel_key")
        out_path = fm.get("out_path")
        if not out_path or not Path(out_path).is_file():
            skip += 1
            continue
        if resume and rel_key in done_keys:
            skip += 1
            continue
        try:
            res = embed_image_file(out_path, defer_lexical_rebuild=True)
            st = res.get("status", "?")
            if st == "done":
                done += 1
                done_keys.add(rel_key)
            elif st == "skipped":
                skip += 1
                done_keys.add(rel_key)
            else:
                err += 1
            if i % 20 == 0:
                elapsed = time.time() - t0
                avg = elapsed / i
                eta = avg * (len(figs_meta) - i) / 60
                print(f"  [{i:>5d}/{len(figs_meta)}] done={done} skip={skip} err={err}  "
                      f"avg={avg:.1f}s ETA={eta:.0f}m")
                # 진행률 저장
                progress["embedded"] = sorted(done_keys)
                _save_progress(progress)
        except Exception as e:
            err += 1
            print(f"  [{i:>5d}] FAIL {Path(out_path).name}: {type(e).__name__}: {e}")

    # 최종 진행률 저장
    progress["embedded"] = sorted(done_keys)
    _save_progress(progress)

    # 후처리
    print("\n=== Phase 3: lexical rebuild + engine reload ===")
    try:
        from services.trichef import lexical_rebuild as _lex
        _lex.rebuild_image_lexical()
        print("  ✓ image lexical 재구축")
    except Exception as e:
        print(f"  ✗ lexical rebuild 실패: {e}")
    try:
        from routes.trichef import reload_engine
        reload_engine()
        print("  ✓ engine reload")
    except Exception as e:
        print(f"  ✗ engine reload 실패: {e}")

    print(f"\n=== 완료: done={done} skip={skip} err={err} "
          f"(총 {(time.time()-t0)/60:.1f}분) ===")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-pdf", type=int, default=0,
                    help="처리할 최대 PDF 수 (0=전체)")
    ap.add_argument("--extract-only", action="store_true",
                    help="Phase 1 (추출) 만 실행")
    ap.add_argument("--embed-only", action="store_true",
                    help="Phase 2 (임베딩) 만 실행 — 추출본 재사용")
    ap.add_argument("--resume", action="store_true",
                    help="중단된 작업 이어 받기")
    # Phase 2 필터링 옵션 — 32K figure 전체는 너무 큼, 우선순위 선별 필요
    ap.add_argument("--min-side", type=int, default=0,
                    help="max(W,H) < N px figure 제외 (예: 200 → 작은 figure 제거)")
    ap.add_argument("--max-per-pdf", type=int, default=0,
                    help="한 PDF 당 최대 N개만 임베딩 (큰 figure 우선)")
    ap.add_argument("--limit-embed", type=int, default=0,
                    help="Phase 2 전체 처리 상한 (0=무제한)")
    args = ap.parse_args()

    if args.embed_only:
        # progress 에서 추출 결과 재구성 (메타 필드 포함)
        # 실제 메타는 progress 에 저장 안 됨 → src_pdf 로부터 figure 디스크 다시 스캔
        progress = _load_progress()
        figs_meta = []
        for pdf_key, rel_keys in progress.get("extracted", {}).items():
            for rk in rel_keys:
                parts = rk.split("/", 2)
                if len(parts) < 3:
                    continue
                stem_part, fname = parts[1], parts[2]
                out_path = EXTRACT_ROOT / stem_part / fname
                # 크기 정보가 필요하면 디스크에서 읽기 (PIL 또는 파일 헤더)
                w = h = 0
                if (args.min_side > 0 or args.max_per_pdf > 0) and out_path.is_file():
                    try:
                        from PIL import Image
                        with Image.open(out_path) as im:
                            w, h = im.size
                    except Exception:
                        pass
                figs_meta.append({
                    "rel_key": rk,
                    "out_path": str(out_path),
                    "src_pdf": pdf_key,
                    "width": w,
                    "height": h,
                })
        phase2_embed(figs_meta, resume=args.resume,
                     min_side=args.min_side,
                     max_per_pdf=args.max_per_pdf,
                     limit=args.limit_embed)
        return

    figs = phase1_extract(limit_pdf=args.limit_pdf, resume=args.resume)
    if not args.extract_only:
        phase2_embed(figs, resume=args.resume,
                     min_side=args.min_side,
                     max_per_pdf=args.max_per_pdf,
                     limit=args.limit_embed)


if __name__ == "__main__":
    main()
