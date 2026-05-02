"""Qwen 5-stage 캡션 종료 후 자동으로 Doc Im_body + sparse 재빌드.

흐름:
  1. Qwen 종료 감지 (모든 5 stage .txt 파일 수가 ids_list 길이와 동일해질 때)
  2. ~30초 추가 대기 (Qwen 프로세스 GPU 메모리 해제)
  3. Doc Im_body 재빌드 (BGE-M3 dense, batch 64, GPU)
  4. Doc sparse + ASF vocab 재빌드 (BGE-M3 sparse, GPU)
  5. 검증: 행 수가 ids 길이와 일치하는지 확인
  6. (옵션) Flask 백엔드 reload_engine() 호출 — 실행 중이면

사용:
  # 1) Qwen 끝날 때까지 자동 대기 + 시작
  python scripts/bgm_doc_rebuild_after_qwen.py

  # 2) 즉시 실행 (Qwen 종료 확인 생략)
  python scripts/bgm_doc_rebuild_after_qwen.py --now

GPU 안전:
  - Qwen 종료 감지 후 추가 30s 대기 → VRAM 해제 보장
  - BGE-M3 batch_size 환경변수로 조정 가능 (기본 64)
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
APP_BACKEND = ROOT / "App" / "backend"
DOC_CACHE = ROOT / "Data" / "embedded_DB" / "Doc"
IMG_CACHE = ROOT / "Data" / "embedded_DB" / "Img"
CAP_DIR = ROOT / "Data" / "extracted_DB" / "Img" / "captions"

QWEN_STAGES = ["title", "tagline", "synopsis", "tags_kr", "tags_en"]


def _ts():
    return datetime.now().strftime("%H:%M:%S")


def _img_ids_count() -> int:
    p = IMG_CACHE / "img_ids.json"
    if not p.is_file():
        return 0
    d = json.loads(p.read_text(encoding="utf-8"))
    return len(d.get("ids", []) if isinstance(d, dict) else d)


def _stage_progress() -> dict[str, int]:
    if not CAP_DIR.is_dir():
        return {s: 0 for s in QWEN_STAGES}
    files = list(CAP_DIR.iterdir())
    return {
        s: sum(1 for f in files if f.name.endswith(f"_{s}.txt"))
        for s in QWEN_STAGES
    }


def wait_for_qwen(poll_sec: int = 60, idle_threshold_sec: int = 60):
    """Qwen 5 stage 모두 완료 또는 60초간 진행 없을 때까지 대기.

    완료 정의: 5 stage 모두 ids 길이의 95% 이상 (실패 5%까지 허용).
    """
    n_ids = _img_ids_count()
    if n_ids == 0:
        print(f"[{_ts()}] img_ids.json 없음 — Qwen 대기 스킵", flush=True)
        return
    threshold = int(n_ids * 0.95)
    print(f"[{_ts()}] Qwen 5 stage 완료 대기. ids={n_ids}, 임계={threshold}", flush=True)

    last_total = -1
    last_change_t = time.time()
    while True:
        prog = _stage_progress()
        total = sum(prog.values())
        all_done = all(v >= threshold for v in prog.values())
        line = " | ".join(f"{s[:6]}:{prog[s]}" for s in QWEN_STAGES)
        print(f"[{_ts()}] {line}  (total={total})", flush=True)
        if all_done:
            print(f"[{_ts()}] Qwen 5 stage 모두 ≥{threshold} — 완료 감지", flush=True)
            return
        if total != last_total:
            last_total = total
            last_change_t = time.time()
        elif time.time() - last_change_t >= idle_threshold_sec:
            # 진행이 멈췄으면 (절전·중단 후 재개 안 됨) 그냥 진행
            print(f"[{_ts()}] {idle_threshold_sec}s 동안 진행 없음 — 강제 진행", flush=True)
            return
        time.sleep(poll_sec)


def _run(cmd: list[str], desc: str) -> tuple[int, str]:
    print(f"\n[{_ts()}] >>> {desc}", flush=True)
    print(f"  $ {' '.join(cmd)}", flush=True)
    t0 = time.time()
    try:
        r = subprocess.run(cmd, check=False, capture_output=False)
        rc = r.returncode
    except Exception as e:
        print(f"  ERROR: {e}", flush=True)
        return 1, str(e)
    elapsed = time.time() - t0
    print(f"[{_ts()}] <<< {desc} 완료 (rc={rc}, {elapsed:.0f}s)", flush=True)
    return rc, ""


def rebuild_im_body(workers: int = 8, batch_size: int = 64) -> int:
    cmd = [
        sys.executable, "-u", str(ROOT / "scripts" / "rebuild_doc_body_fast.py"),
        "--workers", str(workers),
        "--batch-size", str(batch_size),
    ]
    rc, _ = _run(cmd, "Im_body 재빌드 (BGE-M3 dense)")
    return rc


def rebuild_sparse() -> int:
    """rebuild_doc_lexical() 직접 호출 — Doc sparse + ASF + vocab."""
    print(f"\n[{_ts()}] >>> Doc sparse + ASF 재빌드 (BGE-M3 sparse)", flush=True)
    t0 = time.time()
    sys.path.insert(0, str(APP_BACKEND))
    try:
        from services.trichef.lexical_rebuild import rebuild_doc_lexical
        result = rebuild_doc_lexical()
        print(f"  결과: {json.dumps(result, ensure_ascii=False)}", flush=True)
        rc = 0 if not result.get("skipped") else 2
    except Exception as e:
        print(f"  ERROR: {e}", flush=True)
        rc = 1
    elapsed = time.time() - t0
    print(f"[{_ts()}] <<< Doc sparse 재빌드 완료 (rc={rc}, {elapsed:.0f}s)", flush=True)
    return rc


def run_easyocr_pending() -> int:
    """logs/ocr_pending.json 의 169 페이지를 EasyOCR 로 처리.

    ko + en 동시 인식. 각 페이지 → page_text/<stem>/p####.txt 저장.
    GPU 우선 (CUDA available 시), 실패 시 CPU.
    """
    print(f"\n[{_ts()}] >>> EasyOCR 처리 (남은 169 미커버 페이지)", flush=True)
    t0 = time.time()
    pending_path = ROOT / "logs" / "ocr_pending.json"
    if not pending_path.is_file():
        print(f"  ocr_pending.json 없음 — 스킵", flush=True)
        return 0
    pending = json.loads(pending_path.read_text(encoding="utf-8")).get("items", [])
    if not pending:
        print(f"  대상 0건 — 스킵", flush=True)
        return 0

    try:
        import easyocr  # type: ignore
    except ImportError:
        print(f"  easyocr 미설치 — `pip install easyocr` 후 재실행", flush=True)
        return 1

    page_text_root = ROOT / "Data" / "extracted_DB" / "Doc" / "page_text"
    page_image_root = ROOT / "Data" / "extracted_DB" / "Doc" / "page_images"

    # GPU 시도 (Qwen·BGE-M3 종료 후이므로 사용 가능)
    try:
        reader = easyocr.Reader(["ko", "en"], gpu=True, verbose=False)
    except Exception as e:
        print(f"  GPU 모드 실패, CPU fallback: {e}", flush=True)
        reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)

    n_done = 0
    n_fail = 0
    n_skip = 0
    for i, item in enumerate(pending, 1):
        stem = item.get("stem", "")
        page = item.get("page", 0)
        out_dir = page_text_root / stem
        out_path = out_dir / f"p{page:04d}.txt"
        if out_path.is_file():
            n_skip += 1
            continue
        img_path = page_image_root / stem / f"p{page:04d}.jpg"
        if not img_path.is_file():
            n_fail += 1
            continue
        try:
            results = reader.readtext(str(img_path), detail=0, paragraph=True)
            text = "\n".join(results).strip()
            if text:
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path.write_text(text, encoding="utf-8")
                n_done += 1
            else:
                n_fail += 1
        except Exception as e:
            n_fail += 1
            if n_fail <= 5:
                print(f"  실패 [{i}]: {stem[:40]}/p{page:04d} - {type(e).__name__}: {str(e)[:80]}",
                      flush=True)
        if i % 20 == 0:
            print(f"  {i}/{len(pending)} done={n_done} fail={n_fail} skip={n_skip}",
                  flush=True)

    elapsed = time.time() - t0
    print(f"[{_ts()}] <<< EasyOCR 완료 done={n_done} fail={n_fail} skip={n_skip} ({elapsed:.0f}s)",
          flush=True)
    return 0 if n_done > 0 or n_skip > 0 else 1


def rebuild_image_lexical() -> int:
    """rebuild_image_lexical() 호출 — Image vocab + asf_token_sets + sparse.

    Qwen 5-stage 캡션 변경 후 image 도메인의 sparse·lexical 채널이 비활성 상태
    (sparse row count 불일치). 이를 재계산하여 활성화.
    """
    print(f"\n[{_ts()}] >>> Image lexical 재빌드 (BGE-M3 sparse, Qwen 5-stage 반영)", flush=True)
    t0 = time.time()
    sys.path.insert(0, str(APP_BACKEND))
    try:
        from services.trichef.lexical_rebuild import rebuild_image_lexical as _rebuild
        result = _rebuild()
        print(f"  결과: {json.dumps(result, ensure_ascii=False)}", flush=True)
        rc = 0 if not result.get("skipped") else 2
    except Exception as e:
        print(f"  ERROR: {e}", flush=True)
        rc = 1
    elapsed = time.time() - t0
    print(f"[{_ts()}] <<< Image lexical 재빌드 완료 (rc={rc}, {elapsed:.0f}s)", flush=True)
    return rc


def verify() -> bool:
    """행 수 일치 검증."""
    import numpy as np
    print(f"\n[{_ts()}] >>> 검증 — 행 수 일치 확인", flush=True)
    ids = json.loads((DOC_CACHE / "doc_page_ids.json").read_text(encoding="utf-8"))
    ids_list = ids.get("ids", []) if isinstance(ids, dict) else ids
    n_total = len(ids_list)
    print(f"  doc_page_ids: {n_total}", flush=True)

    ok = True
    for fname in ["cache_doc_page_Im.npy", "cache_doc_page_Im_body.npy",
                  "cache_doc_page_Re.npy", "cache_doc_page_Z.npy"]:
        p = DOC_CACHE / fname
        if p.is_file():
            a = np.load(p, mmap_mode="r")
            match = a.shape[0] == n_total
            mark = "✓" if match else "✗"
            print(f"  {mark} {fname:<40} shape={tuple(a.shape)}", flush=True)
            if not match:
                ok = False
        else:
            print(f"  - {fname:<40} (없음)", flush=True)

    sp_path = DOC_CACHE / "cache_doc_page_sparse.npz"
    if sp_path.is_file():
        from scipy.sparse import load_npz
        sp = load_npz(str(sp_path))
        match = sp.shape[0] == n_total
        mark = "✓" if match else "✗"
        print(f"  {mark} cache_doc_page_sparse.npz       shape={tuple(sp.shape)} nnz={sp.nnz}",
              flush=True)
        if not match:
            ok = False

    return ok


def reload_backend_engine_if_running():
    """실행 중인 Flask 엔진의 reload 트리거 (선택)."""
    try:
        import requests  # type: ignore
    except ImportError:
        return
    try:
        r = requests.post("http://127.0.0.1:5001/api/trichef/reindex",
                          json={"scope": "document"}, timeout=5)
        if r.ok:
            print(f"[{_ts()}] 백엔드 엔진 재로드 트리거 OK", flush=True)
    except Exception:
        # 백엔드 미실행 시 무시
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", action="store_true",
                        help="Qwen 종료 확인 생략 — 즉시 실행 (GPU 충돌 위험)")
    parser.add_argument("--gpu-cooldown", type=int, default=30,
                        help="Qwen 종료 후 GPU VRAM 해제 대기 (초, 기본 30)")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--skip-im-body", action="store_true")
    parser.add_argument("--skip-sparse", action="store_true")
    parser.add_argument("--skip-image", action="store_true",
                        help="Image 도메인 lexical 재빌드 스킵")
    parser.add_argument("--skip-ocr", action="store_true",
                        help="EasyOCR 처리 스킵")
    args = parser.parse_args()

    if not args.now:
        wait_for_qwen()
        print(f"[{_ts()}] {args.gpu_cooldown}s 대기 — GPU VRAM 해제", flush=True)
        time.sleep(args.gpu_cooldown)

    rc = 0
    if not args.skip_im_body:
        rc1 = rebuild_im_body(workers=args.workers, batch_size=args.batch_size)
        if rc1 != 0:
            rc = rc1
            print(f"[{_ts()}] Im_body 실패 — sparse 단계 스킵", flush=True)
            return rc

    if not args.skip_sparse:
        rc2 = rebuild_sparse()
        if rc2 != 0:
            rc = rc2

    # Image 도메인도 함께 재빌드 (Qwen 5-stage 캡션이 image 에 반영되어야 sparse 활성화)
    if not args.skip_image:
        rc3 = rebuild_image_lexical()
        if rc3 != 0:
            rc = rc3

    # EasyOCR — 169 미커버 페이지 처리
    if not args.skip_ocr:
        rc4 = run_easyocr_pending()
        # OCR 후 새로 생긴 page_text 를 sparse 에 반영하기 위해 doc sparse 한 번 더
        if rc4 == 0 and not args.skip_sparse:
            print(f"\n[{_ts()}] EasyOCR 결과 반영 — Doc sparse 재빌드 (v2)", flush=True)
            rebuild_sparse()

    ok = verify()
    if not ok:
        print(f"\n[{_ts()}] ⚠ 검증 실패 — 일부 행 수 불일치", flush=True)
        rc = max(rc, 2)
    else:
        print(f"\n[{_ts()}] ✓ 모든 행 수 일치", flush=True)

    reload_backend_engine_if_running()
    print(f"\n[{_ts()}] 전체 완료 (rc={rc})", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
