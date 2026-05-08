"""overnight_orchestrator.py — 야간 자동 실행 오케스트레이터 (23:00 ~ 07:30)

단계:
  Step A (23:00~23:15) : 진단 — 캡션 품질 정량 측정
  Step B (23:15~01:15) : Doc 한국어 요약 생성 (gemma:12b Ollama)
  Step C (01:15~07:10) : Image 5-stage 재캡셔닝 (Qwen2.5-VL-3B)
  07:10~07:25         : 체크포인트 저장 + 진행 보고

아침 재개 (09:00~) : morning_resume.py 실행

체크포인트: Data/embedded_DB/_overnight_progress.json
로그       : logs/overnight_YYYYMMDD.log
"""
from __future__ import annotations
import sys, json, subprocess, time, signal, os
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ─────────── 경로 설정 ───────────
ROOT       = Path(__file__).resolve().parents[3]
SCRIPTS    = Path(__file__).resolve().parent
LOGS_DIR   = ROOT / "logs"
PROG_PATH  = ROOT / "Data" / "embedded_DB" / "_overnight_progress.json"
LOGS_DIR.mkdir(exist_ok=True)

LOG_FILE   = LOGS_DIR / f"overnight_{datetime.now().strftime('%Y%m%d_%H%M')}.log"

# ─────────── 시간 설정 ───────────
# 07:20 이후에는 새 Step 시작 금지, 현재 Step 즉시 중단 신호
CUTOFF_HOUR   = 7
CUTOFF_MINUTE = 20

def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def _past_cutoff() -> bool:
    now = datetime.now()
    cutoff = now.replace(hour=CUTOFF_HOUR, minute=CUTOFF_MINUTE, second=0, microsecond=0)
    # 만약 자정 이후라면 (23시 시작 → 익일 07:20)
    if now.hour < 12:
        return now >= cutoff
    return False  # 23시대는 아직 시간 여유

def _minutes_left() -> float:
    now = datetime.now()
    if now.hour < 12:
        cutoff = now.replace(hour=CUTOFF_HOUR, minute=CUTOFF_MINUTE, second=0, microsecond=0)
        return (cutoff - now).total_seconds() / 60
    else:
        # 23시대 → 내일 07:20까지
        tomorrow = now.date() + timedelta(days=1)
        cutoff = datetime.combine(tomorrow, datetime.min.time()).replace(
            hour=CUTOFF_HOUR, minute=CUTOFF_MINUTE)
        return (cutoff - now).total_seconds() / 60

def _load_progress() -> dict:
    if PROG_PATH.exists():
        try:
            return json.loads(PROG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "session_start": datetime.now().isoformat(),
        "step_a_done": False,
        "step_b_done": False,
        "step_b_doc_count": 0,
        "step_c_done": False,
        "step_c_stages_done": [],
        "step_d_done": False,
        "step_e_done": False,
    }

def _save_progress(prog: dict):
    prog["last_updated"] = datetime.now().isoformat()
    PROG_PATH.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")

def _run_step(cmd: list[str], step_name: str, timeout_min: float | None = None) -> int:
    """subprocess 실행. timeout_min 이 있으면 시간 초과 시 SIGTERM."""
    _log(f"[{step_name}] 시작: {' '.join(cmd)}")
    t0 = time.time()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT / "App" / "backend"),
    )
    deadline = (time.time() + timeout_min * 60) if timeout_min else None
    try:
        while True:
            line = proc.stdout.readline()
            if line:
                _log(f"  [{step_name}] {line.rstrip()}")
            if proc.poll() is not None:
                break
            if deadline and time.time() > deadline:
                _log(f"  [{step_name}] ⏰ 시간 초과 ({timeout_min:.0f}분) → 프로세스 종료")
                proc.terminate()
                proc.wait(timeout=30)
                return -1  # timeout
            if _past_cutoff():
                _log(f"  [{step_name}] ⏰ 전체 마감 시간 도달 → 프로세스 종료")
                proc.terminate()
                proc.wait(timeout=30)
                return -2  # global cutoff
    except KeyboardInterrupt:
        proc.terminate()
        raise
    rc = proc.returncode
    elapsed = time.time() - t0
    _log(f"[{step_name}] 완료 rc={rc} ({elapsed/60:.1f}분)")
    return rc


def main():
    _log("=" * 60)
    _log("야간 오케스트레이터 시작")
    _log(f"종료 예정: {CUTOFF_HOUR:02d}:{CUTOFF_MINUTE:02d} (남은 시간: {_minutes_left():.0f}분)")
    _log("=" * 60)

    prog = _load_progress()
    _log(f"체크포인트: {PROG_PATH}")

    py = sys.executable

    # ═══════════════════════════════════════════
    # Step A — 진단 (15분)
    # ═══════════════════════════════════════════
    if not prog["step_a_done"]:
        if _past_cutoff():
            _log("[Step A] 마감 시간 도달, 스킵")
        else:
            _log("\n━━━ Step A: 진단 ━━━")
            rc = _run_step(
                [py, str(SCRIPTS / "step_a_diag.py")],
                "StepA", timeout_min=20
            )
            prog["step_a_done"] = (rc >= 0)
            _save_progress(prog)
    else:
        _log("[Step A] 이미 완료, 스킵")

    # ═══════════════════════════════════════════
    # Step B — Doc 한국어 요약 생성 (최대 2h)
    # ═══════════════════════════════════════════
    if not prog["step_b_done"]:
        if _past_cutoff():
            _log("[Step B] 마감 시간 도달, 스킵")
        else:
            _log("\n━━━ Step B: Doc 한국어 요약 생성 ━━━")
            mins_left = _minutes_left()
            # Step C를 위해 최소 4.5h 남겨둠
            step_b_budget = max(20, mins_left - 275)
            _log(f"  Step B 예산: {step_b_budget:.0f}분")
            rc = _run_step(
                [py, str(SCRIPTS / "gen_doc_summaries_gemma.py")],
                "StepB", timeout_min=step_b_budget
            )
            prog["step_b_done"] = (rc == 0)
            _save_progress(prog)
    else:
        _log("[Step B] 이미 완료, 스킵")

    # ═══════════════════════════════════════════
    # Step C — Image 재캡셔닝 Qwen2.5-VL-3B (최대 마감까지)
    # ═══════════════════════════════════════════
    if not prog["step_c_done"]:
        if _past_cutoff():
            _log("[Step C] 마감 시간 도달, 스킵")
        else:
            _log("\n━━━ Step C: Image 재캡셔닝 (resume 가능) ━━━")
            mins_left = _minutes_left()
            # 마감 10분 전까지 실행
            step_c_budget = max(10, mins_left - 10)
            _log(f"  Step C 예산: {step_c_budget:.0f}분 (script 내부 resume 자동)")

            # 1차: title/tagline/synopsis (핵심 3단계)
            stages_priority = "title,tagline,synopsis"
            rc = _run_step(
                [py, str(ROOT / "scripts" / "rebuild_img_qwen_full_caption.py"),
                 "--stage", stages_priority],
                "StepC_part1", timeout_min=step_c_budget
            )
            # timeout이어도 일부 완료 → 내일 재개 가능
            if not _past_cutoff() and _minutes_left() > 15:
                # tags도 시도
                _run_step(
                    [py, str(ROOT / "scripts" / "rebuild_img_qwen_full_caption.py"),
                     "--stage", "tags_kr,tags_en"],
                    "StepC_part2", timeout_min=_minutes_left() - 10
                )
            prog["step_c_done"] = (rc == 0)
            _save_progress(prog)
    else:
        _log("[Step C] 이미 완료, 스킵")

    # ═══════════════════════════════════════════
    # 체크포인트 저장 + 진행 보고
    # ═══════════════════════════════════════════
    _log("\n━━━ 야간 작업 종료 보고 ━━━")
    _log(f"  Step A (진단): {'✅' if prog['step_a_done'] else '⏭ 미완'}")
    _log(f"  Step B (Doc 요약): {'✅' if prog['step_b_done'] else '⏭ 미완'}")
    _log(f"  Step C (Image 재캡셔닝): {'✅' if prog['step_c_done'] else '⏭ 미완 (resume 가능)'}")
    _log(f"\n  → 09:00 에 morning_resume.py 를 실행하여 계속하세요.")
    _log(f"     cd App/backend && python scripts/morning_resume.py")
    _save_progress(prog)
    _log(f"[완료] 로그: {LOG_FILE}")


if __name__ == "__main__":
    main()
