"""post_qwen_pipeline.py — Qwen tags 완료 후 전체 재빌드+재학습+평가 자동화.

실행 순서:
  1. merge_img_stage_captions    — captions_triple.jsonl 업데이트 (CPU)
  2. rebuild_doc_img_asf          — Image ASF vocab 재빌드 (CPU)
  3. rebuild_im_cache --img-only  — Image Im 채널 재임베딩 (GPU ~15min)
  4. fix_im_body_55rows --embed-only — Doc Im_body 55행 패치 (GPU ~5min)
  5. bgm_enrich_text              — BGM 한국어 설명 재빌드 + CLAP index (GPU ~5min)
  6. Flask 서버 시작
  7. mplc_collect_features        — KO+EN 피처 수집 (~5min)
  8. mplc_train                   — MPLC 재학습 (~1min)
  9. Flask 서버 재시작 (새 weights 로드)
 10. evaluate_yplus_250           — 250케이스 최종 평가
 11. evaluate_xlang_50            — Cross-lingual 50케이스 평가

사용:
  python scripts/post_qwen_pipeline.py
  python scripts/post_qwen_pipeline.py --from-step 3   # 특정 단계부터 재개
"""
from __future__ import annotations
import argparse
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT      = Path(__file__).resolve().parents[1]
BACKEND   = ROOT / "App" / "backend"
PYTHON    = sys.executable

SERVER_PID_FILE = ROOT / "logs" / "server.pid"
SERVER_LOG      = ROOT / "logs" / "server_pipeline.log"
PIPELINE_LOG    = ROOT / "logs" / "post_qwen_pipeline.log"

ROOT.joinpath("logs").mkdir(exist_ok=True)


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    full = f"[{ts}] {msg}"
    print(full, flush=True)
    with PIPELINE_LOG.open("a", encoding="utf-8") as f:
        f.write(full + "\n")


def run(cmd: list[str], cwd: Path, step_name: str, timeout: int = 3600) -> bool:
    log(f">>> {step_name}")
    log(f"    cmd: {' '.join(cmd)}")
    log(f"    cwd: {cwd}")
    t0 = time.time()
    try:
        r = subprocess.run(
            cmd, cwd=str(cwd),
            capture_output=False,
            timeout=timeout,
        )
        elapsed = time.time() - t0
        if r.returncode == 0:
            log(f"    OK ({elapsed:.1f}s)")
            return True
        else:
            log(f"    FAILED returncode={r.returncode} ({elapsed:.1f}s)")
            return False
    except subprocess.TimeoutExpired:
        log(f"    TIMEOUT after {timeout}s")
        return False
    except Exception as e:
        log(f"    ERROR: {e}")
        return False


def start_server() -> int | None:
    """Flask 서버 백그라운드 시작 → PID 반환."""
    import os
    log("Flask 서버 시작 중...")
    SERVER_LOG.parent.mkdir(exist_ok=True)
    with open(SERVER_LOG, "w", encoding="utf-8") as fout:
        proc = subprocess.Popen(
            [PYTHON, "app.py"],
            cwd=str(BACKEND),
            stdout=fout,
            stderr=fout,
        )
    # PID 저장
    SERVER_PID_FILE.write_text(str(proc.pid))
    log(f"서버 PID: {proc.pid} (log: {SERVER_LOG.name})")
    return proc.pid


def wait_server_ready(max_wait: int = 120) -> bool:
    """서버 /api/health 응답 대기."""
    log("서버 ready 대기 중...")
    t0 = time.time()
    while time.time() - t0 < max_wait:
        try:
            with urllib.request.urlopen("http://127.0.0.1:5001/api/health", timeout=5) as r:
                if r.status == 200:
                    log(f"서버 ready ({time.time()-t0:.1f}s)")
                    return True
        except Exception:
            pass
        time.sleep(5)
    log(f"서버 ready 실패 ({max_wait}s timeout)")
    return False


def stop_server() -> None:
    """PID 파일로 서버 종료."""
    if not SERVER_PID_FILE.exists():
        log("PID 파일 없음 — 서버 종료 건너뜀")
        return
    try:
        pid = int(SERVER_PID_FILE.read_text().strip())
        import signal, os
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
        log(f"서버 PID {pid} 종료")
        time.sleep(3)
        SERVER_PID_FILE.unlink(missing_ok=True)
    except Exception as e:
        log(f"서버 종료 오류: {e}")


STEPS = [
    # (step_num, name, cmd, cwd, timeout_sec)
    (1, "merge_img_stage_captions",
     [PYTHON, "scripts/merge_img_stage_captions.py"],
     BACKEND, 120),

    (2, "rebuild_doc_img_asf",
     [PYTHON, "scripts/rebuild_doc_img_asf.py"],
     BACKEND, 300),

    (3, "rebuild_im_cache_img_only",
     [PYTHON, "scripts/rebuild_im_cache_all.py", "--img-only"],
     BACKEND, 3600),

    (4, "fix_im_body_55rows_embed",
     [PYTHON, "scripts/fix_im_body_55rows.py", "--embed-only"],
     ROOT, 600),

    (5, "bgm_enrich_text",
     [PYTHON, "bin/bgm_enrich_text.py"],
     BACKEND, 600),

    # Steps 6-9: server-dependent (handled specially in main)
    # 6 = start server
    # 7 = mplc_collect_features
    # 8 = mplc_train
    # 9 = restart server

    (10, "evaluate_yplus_250",
     [PYTHON, "scripts/evaluate_yplus_250.py"],
     BACKEND, 600),

    (11, "evaluate_xlang_50",
     [PYTHON, "scripts/evaluate_xlang_50.py"],
     BACKEND, 300),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-step", type=int, default=1, help="재개할 단계 번호")
    parser.add_argument("--skip-server", action="store_true", help="서버 시작 건너뜀 (이미 실행 중)")
    args = parser.parse_args()

    log(f"=== post_qwen_pipeline 시작 (from step {args.from_step}) ===")

    # Steps 1-5: GPU/CPU rebuild (no server needed)
    for step_num, name, cmd, cwd, timeout in STEPS[:5]:
        if step_num < args.from_step:
            log(f"  Skip step {step_num} ({name})")
            continue
        ok = run(cmd, cwd, f"Step {step_num}: {name}", timeout)
        if not ok:
            log(f"ABORT: step {step_num} failed. Re-run with --from-step {step_num}")
            sys.exit(1)

    # Step 6: Start server
    if args.from_step <= 6:
        if args.skip_server:
            log("Step 6: 서버 이미 실행 중 (--skip-server)")
        else:
            # Kill any existing server
            stop_server()
            time.sleep(2)
            pid = start_server()
            if not wait_server_ready(180):
                log("ABORT: 서버 시작 실패")
                sys.exit(1)

    # Step 7: MPLC feature collection (KO+EN)
    if args.from_step <= 7:
        ok = run(
            [PYTHON, "scripts/mplc_collect_features.py"],
            BACKEND, "Step 7: mplc_collect_features (KO+EN)", 600
        )
        if not ok:
            log("ABORT: mplc_collect_features failed")
            sys.exit(1)

    # Step 8: MPLC retrain
    if args.from_step <= 8:
        ok = run(
            [PYTHON, "scripts/mplc_train.py"],
            BACKEND, "Step 8: mplc_train", 120
        )
        if not ok:
            log("ABORT: mplc_train failed")
            sys.exit(1)

    # Step 9: Restart server to load new MPLC weights
    if args.from_step <= 9:
        log("Step 9: 서버 재시작 (새 MPLC weights 로드)")
        stop_server()
        time.sleep(2)
        start_server()
        if not wait_server_ready(180):
            log("ABORT: 서버 재시작 실패")
            sys.exit(1)

    # Steps 10-11: Evaluations
    for step_num, name, cmd, cwd, timeout in STEPS[5:]:
        if step_num < args.from_step:
            log(f"  Skip step {step_num} ({name})")
            continue
        ok = run(cmd, cwd, f"Step {step_num}: {name}", timeout)
        if not ok:
            log(f"WARNING: step {step_num} failed — continuing")

    log("=== post_qwen_pipeline 완료 ===")
    log(f"  결과 확인: {ROOT / 'md'}")


if __name__ == "__main__":
    main()
