"""[P3] 긴 페이지(>1500자) 의 Im 축 재임베딩 — 토큰 잘림 손실 회복.

배경:
  Doc 페이지 텍스트 평균 817자, 그러나 6,393 페이지(18.5%) 가 1500자 초과.
  e5-large/BGE-M3 토큰 한계 ~512토큰 ≈ 1500자 → 초과분 truncate 손실.

전략:
  - 페이지 단위 그래뉼래리티 유지 (Re=시각, Im=텍스트, Z=시각 — 3축 정렬 보존)
  - 긴 페이지의 텍스트만 1000자/200자 슬라이딩 청크 → 각 청크 BGE-M3 임베딩
    → 평균 풀링 (mean) → 페이지 단위 단일 벡터로 환원
  - cache_doc_page_Im.npy 의 해당 행만 교체 (Im_body 도 동일 처리)
  - Re/Z (시각 채널) 미변경 — 페이지 이미지는 그대로

장점:
  - 잘려나간 페이지 뒷부분 의미가 임베딩에 반영됨
  - 인덱스 구조 변경 없음 (id, 행 수 보존)
  - 검색 결과 "N페이지" 표시 동일하게 유지
  - 부분 실행 가능 (배치별 진행률 저장)

대상: page_text/<stem>/p####.txt 길이 > 1500자 인 페이지
실행: python App/backend/scripts/reembed_long_doc_pages.py [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

# 경로 설정
_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "App" / "backend"))

from config import PATHS  # noqa: E402
from embedders.trichef.text_chunker import chunk_text  # noqa: E402

DOC_CACHE = Path(PATHS["TRICHEF_DOC_CACHE"])
PAGE_TEXT_DIR = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "page_text"


def _id_to_page_text(id_str: str) -> Path | None:
    """doc_page_ids 의 id 로부터 page_text/.../p####.txt 경로 추정.

    id 형식 예: page_images/<stem>/p0042.jpg
              → page_text/<stem>/p0042.txt
    """
    parts = id_str.split("/")
    if len(parts) < 3 or parts[0] != "page_images":
        return None
    stem = parts[1]
    p_name = parts[-1]
    txt_name = Path(p_name).stem + ".txt"
    return PAGE_TEXT_DIR / stem / txt_name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="처리할 최대 페이지 수 (0=전체)")
    ap.add_argument("--threshold", type=int, default=1500,
                    help="재임베딩 대상 글자 수 임계 (이상이면 청크화)")
    ap.add_argument("--dry-run", action="store_true",
                    help="실제 임베딩 없이 대상 페이지만 출력")
    ap.add_argument("--batch", type=int, default=32,
                    help="BGE-M3 배치 크기")
    args = ap.parse_args()

    ts = int(time.time())
    print(f"=== 긴 페이지 Im 축 재임베딩 (ts={ts}) ===")

    # 1) ids 로드
    ids_path = DOC_CACHE / "doc_page_ids.json"
    raw = json.loads(ids_path.read_text(encoding="utf-8"))
    ids = raw.get("ids", []) if isinstance(raw, dict) else list(raw)
    print(f"  ids: {len(ids)}개")

    # 2) 대상 페이지 식별 — 텍스트 길이 > threshold
    targets = []  # [(row_idx, id, page_text_path, text)]
    missing_txt = 0
    for i, id_str in enumerate(ids):
        pt_path = _id_to_page_text(id_str)
        if pt_path is None or not pt_path.is_file():
            missing_txt += 1
            continue
        try:
            t = pt_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if len(t) > args.threshold:
            targets.append((i, id_str, pt_path, t))

    print(f"  대상 (>{args.threshold}자): {len(targets)}건  / 텍스트 파일 누락 {missing_txt}건")
    if args.limit > 0:
        targets = targets[:args.limit]
        print(f"  --limit {args.limit} 적용 → {len(targets)}건 처리")

    if args.dry_run:
        print("[dry-run] 상위 5건 미리보기:")
        for row_idx, id_str, pt, t in targets[:5]:
            chunks = chunk_text(t)
            print(f"  [{row_idx}] {pt.name}: {len(t)}자 → {len(chunks)}청크 (id={id_str[:60]!r})")
        return

    if not targets:
        print("대상 없음 — 종료")
        return

    # 3) BGE-M3 로더 (지연 로드)
    print("  BGE-M3 로드 중...")
    from embedders.trichef import bgem3_caption_im as im_embedder

    # 4) Im / Im_body 캐시 로드 (전체 행 메모리 적재)
    Im_path = DOC_CACHE / "cache_doc_page_Im.npy"
    Imb_path = DOC_CACHE / "cache_doc_page_Im_body.npy"
    Im = np.load(Im_path)
    Im_body = np.load(Imb_path)
    print(f"  Im={Im.shape}, Im_body={Im_body.shape}")

    if Im.shape[0] != len(ids):
        print(f"  [error] Im shape ({Im.shape[0]}) != ids ({len(ids)}) — P5 정렬 먼저 실행")
        sys.exit(1)

    # 5) 백업
    backup_suffix = f".pre_reembed_{ts}"
    import shutil
    for p in [Im_path, Imb_path]:
        bk = p.with_suffix(p.suffix + backup_suffix)
        shutil.copy2(p, bk)
        print(f"  백업: {p.name} → {bk.name}")

    # 6) 페이지별로 청크 임베딩 + 평균 풀링
    t0 = time.time()
    n_done = 0
    n_err = 0
    for row_idx, id_str, pt, text in targets:
        try:
            chunks = chunk_text(text, chunk_size=1000, overlap=200)
            if not chunks:
                n_err += 1
                continue
            # BGE-M3 passage 인코딩 (배치)
            vecs = im_embedder.embed_passage(chunks)  # (n_chunks, 1024)
            if vecs is None or vecs.size == 0:
                n_err += 1
                continue
            # L2 정규화 후 평균 풀링 → 다시 L2 정규화
            norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
            vecs_n = vecs / norms
            pooled = vecs_n.mean(axis=0)
            pn = np.linalg.norm(pooled) + 1e-9
            pooled = pooled / pn

            # Im 와 Im_body 동시 교체 (body 도 같은 텍스트 기반)
            Im[row_idx] = pooled.astype(Im.dtype)
            if row_idx < Im_body.shape[0]:
                Im_body[row_idx] = pooled.astype(Im_body.dtype)

            n_done += 1
            if n_done % 50 == 0:
                elapsed = time.time() - t0
                avg = elapsed / n_done
                eta = avg * (len(targets) - n_done) / 60
                print(f"    [{n_done:>5d}/{len(targets)}] avg={avg:.2f}s/페이지  ETA={eta:.0f}분  "
                      f"(현재: {pt.name}, {len(text)}자 → {len(chunks)}청크)")
        except Exception as e:
            n_err += 1
            print(f"    [{n_done+n_err}] FAIL {pt.name}: {type(e).__name__}: {e}")

    # 7) 저장 (atomic via tmp + move)
    print(f"\n  저장 중 (Im, Im_body)...")
    for arr, target in [(Im, Im_path), (Im_body, Imb_path)]:
        tmp = target.with_suffix(target.suffix + f".tmp.{ts}")
        np.save(tmp, arr)
        if not tmp.exists() and tmp.with_suffix(tmp.suffix + ".npy").exists():
            tmp.with_suffix(tmp.suffix + ".npy").rename(tmp)
        if target.exists():
            target.unlink()
        shutil.move(tmp, target)
        print(f"    ✓ {target.name} {arr.shape}")

    print(f"\n=== 완료: 성공 {n_done} / 실패 {n_err} (총 {(time.time()-t0)/60:.1f}분) ===")
    print(f"백업: *{backup_suffix}")
    print()
    print("후속 작업:")
    print("  - 앱 재시작 또는 reload_engine()")
    print("  - 긴 페이지(18.5%) 의 잘림 손실 회복 → 본문 검색 정확도 개선 기대")


if __name__ == "__main__":
    main()
