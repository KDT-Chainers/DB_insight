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


def _check_qwen_completeness() -> dict:
    """Qwen 5-stage 완료율 체크."""
    n_ids = _img_ids_count()
    if n_ids == 0:
        return {"ok": True, "n_ids": 0, "stages": {}, "skipped": True}
    stages = _stage_progress()
    threshold = int(n_ids * 0.95)
    incomplete = [s for s, v in stages.items() if v < threshold]
    return {
        "ok": len(incomplete) == 0,
        "n_ids": n_ids,
        "stages": stages,
        "incomplete": incomplete,
        "threshold": threshold,
    }


def _check_doc_rows() -> dict:
    """Doc 도메인 행 수 일치."""
    import numpy as np
    ids = json.loads((DOC_CACHE / "doc_page_ids.json").read_text(encoding="utf-8"))
    n = len(ids.get("ids", []) if isinstance(ids, dict) else ids)
    out = {"ok": True, "n_ids": n, "files": {}}
    for fname in ["cache_doc_page_Re.npy", "cache_doc_page_Im.npy",
                  "cache_doc_page_Im_body.npy", "cache_doc_page_Z.npy"]:
        p = DOC_CACHE / fname
        if p.is_file():
            try:
                rows = np.load(p, mmap_mode="r").shape[0]
            except Exception:
                rows = -1
            out["files"][fname] = rows
            if rows != n:
                out["ok"] = False
    sp_path = DOC_CACHE / "cache_doc_page_sparse.npz"
    if sp_path.is_file():
        try:
            from scipy.sparse import load_npz
            rows = load_npz(str(sp_path)).shape[0]
        except Exception:
            rows = -1
        out["files"]["cache_doc_page_sparse.npz"] = rows
        if rows != n:
            out["ok"] = False
    asf_path = DOC_CACHE / "asf_token_sets.json"
    if asf_path.is_file():
        try:
            asf_n = len(json.loads(asf_path.read_text(encoding="utf-8")))
        except Exception:
            asf_n = -1
        out["files"]["asf_token_sets.json"] = asf_n
        if asf_n != n:
            out["ok"] = False
    return out


def _check_image_rows() -> dict:
    """Image 도메인 행 수 일치."""
    import numpy as np
    ids = json.loads((IMG_CACHE / "img_ids.json").read_text(encoding="utf-8"))
    n = len(ids.get("ids", []) if isinstance(ids, dict) else ids)
    out = {"ok": True, "n_ids": n, "files": {}}
    for fname in ["cache_img_Re_siglip2.npy", "cache_img_Z_dinov2.npy",
                  "cache_img_Im_L1.npy", "cache_img_Im_L2.npy", "cache_img_Im_L3.npy",
                  "cache_img_Im_e5cap.npy"]:
        p = IMG_CACHE / fname
        if p.is_file():
            try:
                rows = np.load(p, mmap_mode="r").shape[0]
            except Exception:
                rows = -1
            out["files"][fname] = rows
            if rows != n:
                out["ok"] = False
    sp_path = IMG_CACHE / "cache_img_sparse.npz"
    if sp_path.is_file():
        try:
            from scipy.sparse import load_npz
            rows = load_npz(str(sp_path)).shape[0]
        except Exception:
            rows = -1
        out["files"]["cache_img_sparse.npz"] = rows
        if rows != n:
            out["ok"] = False
    asf_path = IMG_CACHE / "asf_token_sets.json"
    if asf_path.is_file():
        try:
            asf_n = len(json.loads(asf_path.read_text(encoding="utf-8")))
        except Exception:
            asf_n = -1
        out["files"]["asf_token_sets.json"] = asf_n
        if asf_n != n:
            out["ok"] = False
    return out


def _check_page_text_coverage() -> dict:
    """page_text 커버리지 (≥99% 목표)."""
    page_text = ROOT / "Data" / "extracted_DB" / "Doc" / "page_text"
    ids = json.loads((DOC_CACHE / "doc_page_ids.json").read_text(encoding="utf-8"))
    ids_list = ids.get("ids", []) if isinstance(ids, dict) else ids
    n = len(ids_list)
    if n == 0 or not page_text.is_dir():
        return {"ok": False, "covered": 0, "total": n, "ratio": 0.0}
    import re
    pattern = re.compile(r"^page_images/(.+)/p(\d+)\.(?:jpg|png)$")
    n_covered = 0
    for rid in ids_list:
        m = pattern.match(rid)
        if not m:
            continue
        stem, page = m.group(1), int(m.group(2))
        if (page_text / stem / f"p{page:04d}.txt").is_file():
            n_covered += 1
    ratio = n_covered / n
    return {"ok": ratio >= 0.99, "covered": n_covered, "total": n, "ratio": round(ratio, 4)}


def _check_smoke_searches() -> dict:
    """5도메인 1쿼리씩 빠른 search 동작 확인 (CPU)."""
    import os as _os
    _os.environ["FORCE_CPU"] = "1"
    sys.path.insert(0, str(APP_BACKEND))
    out = {"ok": True, "domains": {}}
    try:
        from routes.trichef import _get_engine
        from services.bgm.search_engine import get_engine as get_bgm
        engine = _get_engine()
        bgm = get_bgm()
    except Exception as e:
        return {"ok": False, "error": f"engine load failed: {e}"}

    queries = {
        "doc_page": "취업",
        "image":    "산",
        "movie":    "회의",
        "music":    "안녕",
        "bgm":      "잔잔한",
    }
    for d, q in queries.items():
        try:
            t = time.time()
            if d == "bgm":
                r = bgm.search(q, top_k=1)
                n = len(r.get("results", []))
            elif d in ("movie", "music"):
                hits = engine.search_av(q, domain=d, topk=1)
                n = len(hits)
            else:
                hits = engine.search(q, domain=d, topk=1, use_lexical=True, use_asf=True)
                n = len(hits)
            elapsed = round((time.time() - t) * 1000, 1)
            ok_d = n > 0
            out["domains"][d] = {"ok": ok_d, "n": n, "ms": elapsed}
            if not ok_d:
                out["ok"] = False
        except Exception as e:
            out["domains"][d] = {"ok": False, "error": str(e)[:120]}
            out["ok"] = False
    return out


def final_verify_with_retry(args) -> dict:
    """
    종합 검증 + 1회 자동 재시도. 결과를 logs/post_rebuild_report.json 저장.

    Pass 정의: Qwen 95%+ AND Doc 행 일치 AND Image 행 일치 AND page_text 99%+ AND
              5도메인 smoke search 성공.
    """
    def _run_checks() -> dict:
        return {
            "qwen":       _check_qwen_completeness(),
            "doc_rows":   _check_doc_rows(),
            "image_rows": _check_image_rows(),
            "page_text":  _check_page_text_coverage(),
            "smoke":      _check_smoke_searches(),
        }

    print(f"\n[{_ts()}] === FINAL VERIFY (1차) ===", flush=True)
    r1 = _run_checks()
    fails = [k for k, v in r1.items() if not v.get("ok", False)]
    print(f"  qwen ok=     {r1['qwen']['ok']}  (5 stage 완료율)", flush=True)
    print(f"  doc rows ok= {r1['doc_rows']['ok']}  (n_ids={r1['doc_rows']['n_ids']}, files={r1['doc_rows']['files']})", flush=True)
    print(f"  img rows ok= {r1['image_rows']['ok']}  (n_ids={r1['image_rows']['n_ids']})", flush=True)
    print(f"  page_text=   {r1['page_text']['ok']}  ({r1['page_text']['ratio']*100:.1f}% covered)", flush=True)
    print(f"  smoke=       {r1['smoke']['ok']}  ({sum(1 for d in r1['smoke'].get('domains', {}).values() if d.get('ok')) }/5 domains)", flush=True)

    final = r1
    retried = False

    if fails and not args.skip_retry:
        print(f"\n[{_ts()}] 재시도 가능 항목: {fails}", flush=True)
        retried = True
        if "doc_rows" in fails:
            if not r1["doc_rows"]["files"].get("cache_doc_page_Im_body.npy") == r1["doc_rows"]["n_ids"]:
                rebuild_im_body(workers=args.workers, batch_size=args.batch_size)
            rebuild_sparse()
        if "image_rows" in fails:
            rebuild_image_lexical()
        if "page_text" in fails:
            run_easyocr_pending()
            rebuild_sparse()  # OCR 결과 반영
        # 재검증
        print(f"\n[{_ts()}] === FINAL VERIFY (2차, 재시도 후) ===", flush=True)
        r2 = _run_checks()
        final = r2
        print(f"  qwen ok=     {r2['qwen']['ok']}", flush=True)
        print(f"  doc rows ok= {r2['doc_rows']['ok']}", flush=True)
        print(f"  img rows ok= {r2['image_rows']['ok']}", flush=True)
        print(f"  page_text=   {r2['page_text']['ok']}", flush=True)
        print(f"  smoke=       {r2['smoke']['ok']}", flush=True)

    final_pass = all(v.get("ok", False) for v in final.values())
    final["pass"] = final_pass
    final["retried"] = retried

    # 저장
    report_path = ROOT / "logs" / "post_rebuild_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(final, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return final


def print_banner(report: dict):
    """완료 배너 — 한 눈에 PASS/FAIL 확인."""
    if report.get("pass"):
        retry_note = " (after retry)" if report.get("retried") else ""
        msg = f"ALL CHECKS PASSED{retry_note}"
        print(f"""
+========================================+
|                                        |
|  [PASS] {msg:<31} |
|  All searches ready to use.            |
|                                        |
+========================================+
""", flush=True)
    else:
        print(f"""
+========================================+
|                                        |
|  [FAIL] ISSUES DETECTED                |
|  See logs/post_rebuild_report.json     |
|                                        |
+========================================+
""", flush=True)


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
    parser.add_argument("--skip-retry", action="store_true",
                        help="검증 실패 시 자동 재시도 비활성")
    parser.add_argument("--verify-only", action="store_true",
                        help="재빌드 안 하고 검증만 (이미 완료된 작업 점검용)")
    args = parser.parse_args()

    # 검증만 (이미 완료된 작업 점검) — 재빌드 안 함
    if args.verify_only:
        report = final_verify_with_retry(args)
        print_banner(report)
        return 0 if report.get("pass") else 2

    if not args.now:
        wait_for_qwen()
        print(f"[{_ts()}] {args.gpu_cooldown}s 대기 — GPU VRAM 해제", flush=True)
        time.sleep(args.gpu_cooldown)

    rc = 0
    if not args.skip_im_body:
        try:
            rc1 = rebuild_im_body(workers=args.workers, batch_size=args.batch_size)
            if rc1 != 0:
                rc = rc1
                print(f"[{_ts()}] Im_body 실패 (rc={rc1}) — 다음 단계 시도", flush=True)
        except Exception as e:
            print(f"[{_ts()}] Im_body 예외: {e} — 다음 단계 시도", flush=True)
            rc = 1

    if not args.skip_sparse:
        try:
            rc2 = rebuild_sparse()
            if rc2 != 0:
                rc = rc2
        except Exception as e:
            print(f"[{_ts()}] sparse 예외: {e}", flush=True)
            rc = 1

    # Image 도메인도 함께 재빌드 (Qwen 5-stage 캡션이 image 에 반영되어야 sparse 활성화)
    if not args.skip_image:
        try:
            rc3 = rebuild_image_lexical()
            if rc3 != 0:
                rc = rc3
        except Exception as e:
            print(f"[{_ts()}] image lexical 예외: {e}", flush=True)
            rc = 1

    # EasyOCR — 169 미커버 페이지 처리
    if not args.skip_ocr:
        try:
            rc4 = run_easyocr_pending()
            # OCR 후 새로 생긴 page_text 를 sparse 에 반영하기 위해 doc sparse 한 번 더
            if rc4 == 0 and not args.skip_sparse:
                print(f"\n[{_ts()}] EasyOCR 결과 반영 — Doc sparse 재빌드 (v2)", flush=True)
                rebuild_sparse()
        except Exception as e:
            print(f"[{_ts()}] EasyOCR 예외: {e}", flush=True)
            rc = 1

    # ── 최종 검증 + 1회 자동 재시도 ─────────────────────────────────────
    report = final_verify_with_retry(args)
    print_banner(report)
    if not report.get("pass"):
        rc = max(rc, 2)

    reload_backend_engine_if_running()
    print(f"\n[{_ts()}] 전체 완료 (rc={rc}, pass={report.get('pass')})", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
