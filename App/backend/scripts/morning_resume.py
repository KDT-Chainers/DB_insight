"""morning_resume.py — 09:00 아침 재개 오케스트레이터.

야간 overnight_orchestrator.py 완료 후 이어서 실행.
체크포인트 읽어 미완료 단계부터 자동 재개.

단계:
  Step C' : Image 캡션 나머지 stage (tags_kr/tags_en) 재개 (필요 시)
  Step D  : Image stage → captions_triple.jsonl 병합
  Step E  : Doc + Image Im 캐시 재빌드 (BGE-M3)
  Step F  : DOC_IM_ALPHA 최적화 (0.20→0.35 실험)
  Step G  : 250케이스 평가 + cross-lingual 50케이스 평가
  Step H  : 최종 보고서 생성

사용:
  cd App/backend && python scripts/morning_resume.py
"""
from __future__ import annotations
import sys, json, subprocess, time, re
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT     = Path(__file__).resolve().parents[3]
SCRIPTS  = Path(__file__).resolve().parent
LOGS_DIR = ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)
LOG_FILE = LOGS_DIR / f"morning_{datetime.now().strftime('%Y%m%d_%H%M')}.log"
PROG_PATH = ROOT / "Data" / "embedded_DB" / "_overnight_progress.json"

py = sys.executable


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _load_progress() -> dict:
    if PROG_PATH.exists():
        try:
            return json.loads(PROG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_progress(prog: dict):
    prog["last_updated"] = datetime.now().isoformat()
    PROG_PATH.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")


def _run(cmd: list[str], step: str, timeout_min: float = 120) -> int:
    _log(f"[{step}] 시작: {' '.join(str(c) for c in cmd)}")
    t0 = time.time()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT / "App" / "backend"),
    )
    deadline = time.time() + timeout_min * 60
    try:
        while True:
            line = proc.stdout.readline()
            if line:
                _log(f"  {line.rstrip()}")
            if proc.poll() is not None:
                break
            if time.time() > deadline:
                _log(f"  ⏰ 타임아웃({timeout_min:.0f}분) → 종료")
                proc.terminate()
                proc.wait(timeout=30)
                return -1
    except KeyboardInterrupt:
        proc.terminate()
        raise
    rc = proc.returncode
    _log(f"[{step}] 완료 rc={rc} ({(time.time()-t0)/60:.1f}분)")
    return rc


def _check_stage_progress() -> dict[str, int]:
    """Image stage 파일 현황 카운트."""
    cap_dir = ROOT / "Data" / "extracted_DB" / "Img" / "captions"
    if not cap_dir.exists():
        return {}
    counts = {}
    for s in ["title", "tagline", "synopsis", "tags_kr", "tags_en"]:
        counts[s] = len(list(cap_dir.glob(f"*_{s}.txt")))
    return counts


def _patch_doc_im_alpha(new_alpha: float):
    """config.py 의 DOC_IM_ALPHA 값 업데이트."""
    cfg_path = ROOT / "App" / "backend" / "config.py"
    if not cfg_path.exists():
        _log(f"  [경고] config.py 없음, alpha 패치 스킵")
        return
    old_text = cfg_path.read_text(encoding="utf-8")
    new_text = re.sub(
        r'("DOC_IM_ALPHA"\s*:\s*)[\d.]+',
        f'\\g<1>{new_alpha}',
        old_text,
    )
    if new_text != old_text:
        cfg_path.write_text(new_text, encoding="utf-8")
        _log(f"  config.py DOC_IM_ALPHA → {new_alpha}")
    else:
        _log(f"  config.py DOC_IM_ALPHA 패치 실패 (패턴 미매칭)")


def main():
    _log("=" * 60)
    _log("아침 재개 오케스트레이터 시작")
    _log("=" * 60)

    prog = _load_progress()
    _log(f"야간 체크포인트: step_a={prog.get('step_a_done')} "
         f"step_b={prog.get('step_b_done')} step_c={prog.get('step_c_done')}")

    # ─────────────────────────────────────────────
    # Step B' — Doc 요약 나머지 재개 (step_b_done=False 면 resume)
    # gen_doc_summaries_gemma.py 는 summary.caption.json 있으면 자동 스킵
    # ─────────────────────────────────────────────
    if not prog.get("step_b_done"):
        _log("\n━━━ Step B': Doc 요약 나머지 재개 (resume 자동) ━━━")
        rc = _run(
            [py, str(SCRIPTS / "gen_doc_summaries_gemma.py")],
            "StepB_resume", timeout_min=90
        )
        prog["step_b_done"] = (rc == 0)
        _save_progress(prog)
    else:
        _log("[Step B'] 이미 완료, 스킵")

    # ─────────────────────────────────────────────
    # Step C' — Image 나머지 stage 완료 (필요 시)
    # ─────────────────────────────────────────────
    stage_counts = _check_stage_progress()
    _log(f"\n[Stage 현황] {stage_counts}")

    img_ids_path = ROOT / "Data" / "embedded_DB" / "Img" / "img_ids.json"
    total_imgs = 0
    if img_ids_path.exists():
        ids_raw = json.loads(img_ids_path.read_text(encoding="utf-8"))
        ids = ids_raw.get("ids", ids_raw) if isinstance(ids_raw, dict) else ids_raw
        total_imgs = len(ids)

    # tags_kr / tags_en 미완이면 재개
    for stage in ["tags_kr", "tags_en"]:
        done = stage_counts.get(stage, 0)
        if done < total_imgs * 0.9:  # 90% 미만이면 재개
            _log(f"\n━━━ Step C': {stage} 재캡셔닝 재개 ({done}/{total_imgs}) ━━━")
            _run(
                [py, str(ROOT / "scripts" / "rebuild_img_qwen_full_caption.py"),
                 "--stage", stage],
                f"StepC_{stage}", timeout_min=90
            )
        else:
            _log(f"[Step C' {stage}] 충분히 완료 ({done}/{total_imgs}), 스킵")

    # ─────────────────────────────────────────────
    # Step D — captions_triple.jsonl 병합
    # ─────────────────────────────────────────────
    _log("\n━━━ Step D: Image stage 캡션 병합 ━━━")
    rc = _run([py, str(SCRIPTS / "merge_img_stage_captions.py")], "StepD_merge", timeout_min=10)
    prog["step_d_merge_done"] = (rc == 0)
    _save_progress(prog)

    # ─────────────────────────────────────────────
    # Step E — Im 캐시 재빌드 (Doc + Image)
    # ─────────────────────────────────────────────
    if not prog.get("step_e_done"):
        _log("\n━━━ Step E: Im 캐시 재빌드 (BGE-M3) ━━━")

        # Doc Im 재빌드 — Step B 부분 완료여도 실행 (299/421건 생성된 상태)
        doc_cap_count = sum(1 for _ in (
            ROOT / "Data" / "extracted_DB" / "Doc" / "captions"
        ).rglob("summary.caption.json")) if (
            ROOT / "Data" / "extracted_DB" / "Doc" / "captions"
        ).exists() else 0
        _log(f"  Doc summary.caption.json 생성 수: {doc_cap_count}건")
        if doc_cap_count > 0:
            rc = _run(
                [py, str(SCRIPTS / "rebuild_im_cache_all.py"), "--doc-only"],
                "StepE_doc", timeout_min=60
            )
            prog["step_e_doc_done"] = (rc == 0)
            _save_progress(prog)
        else:
            _log("  [Doc 요약 없음] Doc Im 재빌드 스킵")

        # Image Im 재빌드
        rc = _run(
            [py, str(SCRIPTS / "rebuild_im_cache_all.py"), "--img-only"],
            "StepE_img", timeout_min=60
        )
        prog["step_e_img_done"] = (rc == 0)
        prog["step_e_done"] = prog.get("step_e_doc_done", False) or prog.get("step_e_img_done", False)
        _save_progress(prog)
    else:
        _log("[Step E] 이미 완료, 스킵")

    # ─────────────────────────────────────────────
    # Step F — DOC_IM_ALPHA 조정 (0.20 → 0.35)
    #   Doc 요약 생성 완료 시 캡션 품질 향상 → alpha 올릴 수 있음
    # ─────────────────────────────────────────────
    if prog.get("step_e_doc_done"):
        _log("\n━━━ Step F: DOC_IM_ALPHA 0.20 → 0.35 조정 ━━━")
        _patch_doc_im_alpha(0.35)
        prog["doc_im_alpha_updated"] = 0.35
        _save_progress(prog)
    else:
        _log("[Step F] Doc Im 재빌드 미완, alpha 조정 보류 (0.20 유지)")

    # ─────────────────────────────────────────────
    # Step G — 250케이스 성능 평가
    # ─────────────────────────────────────────────
    _log("\n━━━ Step G: 250케이스 평가 (서버 실행 필요) ━━━")
    _log("  [중요] 서버가 실행 중이어야 합니다: python app.py (포트 5001)")
    _log("  서버가 실행 중이지 않으면 평가가 실패합니다.")

    rc = _run(
        [py, str(SCRIPTS / "evaluate_yplus_250.py")],
        "StepG_eval250", timeout_min=30
    )
    prog["step_g_eval_done"] = (rc == 0)
    _save_progress(prog)

    # Cross-lingual 평가
    xlang_script = SCRIPTS / "evaluate_xlang_50.py"
    if xlang_script.exists():
        rc2 = _run(
            [py, str(xlang_script)],
            "StepG_xlang", timeout_min=15
        )
        prog["step_g_xlang_done"] = (rc2 == 0)
        _save_progress(prog)

    # ─────────────────────────────────────────────
    # Step H — 최종 보고서
    # ─────────────────────────────────────────────
    _log("\n━━━ Step H: 최종 보고서 생성 ━━━")
    _gen_final_report(prog)

    _log("\n" + "=" * 60)
    _log("아침 재개 완료!")
    _log(f"로그: {LOG_FILE}")
    _log("=" * 60)


def _gen_final_report(prog: dict):
    """작업 결과 요약 MD 생성."""
    import time as t
    out = ROOT / "md" / "_overnight_final_report.md"
    out.parent.mkdir(exist_ok=True)

    # 최신 평가 결과 읽기
    eval_md = ROOT / "md" / "_yplus_250_eval.md"
    eval_summary = ""
    if eval_md.exists():
        lines = eval_md.read_text(encoding="utf-8").split("\n")
        # 종합 섹션 추출
        in_section = False
        for line in lines[:30]:
            if "## 종합" in line:
                in_section = True
            if in_section:
                eval_summary += line + "\n"
            if in_section and line.startswith("##") and "종합" not in line:
                break

    stage_counts = _check_stage_progress()

    md_lines = [
        "# 야간 작업 최종 보고서",
        f"_생성: {t.strftime('%Y-%m-%d %H:%M:%S')}_\n",
        "## 완료 단계",
        f"| 단계 | 상태 |",
        f"|---|---|",
        f"| Step A: 진단 | {'✅' if prog.get('step_a_done') else '⏭'} |",
        f"| Step B: Doc 한국어 요약 생성 | {'✅' if prog.get('step_b_done') else '⏭'} |",
        f"| Step C: Image 재캡셔닝 | {'✅' if prog.get('step_c_done') else '⏭ (일부완료)'} |",
        f"| Step D: captions_triple 병합 | {'✅' if prog.get('step_d_merge_done') else '⏭'} |",
        f"| Step E: Im 캐시 재빌드 | {'✅' if prog.get('step_e_done') else '⏭'} |",
        f"| Step F: DOC_IM_ALPHA 조정 | {str(prog.get('doc_im_alpha_updated', '유지 0.20'))} |",
        f"| Step G: 250케이스 평가 | {'✅' if prog.get('step_g_eval_done') else '⏭'} |",
        "\n## Image Stage 진행률",
        "| stage | 완료 |", "|---|---|",
    ]
    for s in ["title", "tagline", "synopsis", "tags_kr", "tags_en"]:
        md_lines.append(f"| {s} | {stage_counts.get(s, 0)} |")

    if eval_summary:
        md_lines += ["\n## 250케이스 평가 결과", eval_summary]

    md_lines += [
        "\n## 다음 단계 (필요 시)",
        "- DOC_IM_ALPHA 추가 튜닝 (0.35→0.50 실험)",
        "- MPLC 재훈련 (새 캡션 기반)",
        "- cross-lingual 50케이스 평가 추가",
        "- 서버 재시작 후 사용자 테스트",
    ]

    out.write_text("\n".join(md_lines), encoding="utf-8")
    _log(f"  보고서: {out}")


if __name__ == "__main__":
    main()
