"""scripts/run_overnight_inspection.py — 야간 점검 마스터 실행기.

점검 스크립트 6개를 순서대로 실행하고 최종 Markdown 리포트를 생성한다.
각 단계 실패 시 다음 단계는 계속 진행 (--stop-on-error 로 중단 가능).

실행:
  python scripts/run_overnight_inspection.py
  python scripts/run_overnight_inspection.py --skip-bench   # 벤치 skip (빠른 점검)
  python scripts/run_overnight_inspection.py --stop-on-error
  python scripts/run_overnight_inspection.py --only calib integrity

예상 소요 시간:
  1. check_calibration       ~  1분
  2. check_index_integrity   ~  2분
  3. domain_bench_queries    ~ 30분  (모델 로드 + 35쿼리 × 5도메인)
  4. test_ocr_search         ~ 10분
  5. test_irrelevant_queries ~ 20분
  6. generate_inspection_report ~  1분
  ────────────────────────────────
  합계                       ~ 64분
"""
from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT    = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

STEPS: list[dict] = [
    {
        "key":    "calib",
        "script": "check_calibration.py",
        "label":  "[1/6] 캘리브레이션 점검",
        "est":    "~1분",
    },
    {
        "key":    "integrity",
        "script": "check_index_integrity.py",
        "label":  "[2/6] 인덱스 정합성 점검",
        "est":    "~2분",
    },
    {
        "key":    "bench",
        "script": "domain_bench_queries.py",
        "label":  "[3/6] 도메인별 쿼리 벤치마크",
        "est":    "~30분",
    },
    {
        "key":    "ocr",
        "script": "test_ocr_search.py",
        "label":  "[4/6] 이미지 내 텍스트 검색 진단",
        "est":    "~10분",
    },
    {
        "key":    "irrelevant",
        "script": "test_irrelevant_queries.py",
        "label":  "[5/6] 부적합 쿼리 필터링 점검",
        "est":    "~20분",
    },
    {
        "key":    "report",
        "script": "generate_inspection_report.py",
        "label":  "[6/6] 종합 Markdown 리포트 생성",
        "est":    "~1분",
    },
]


def run_step(script: str, extra_args: list[str]) -> tuple[int, float]:
    """스크립트 실행. (returncode, elapsed_sec) 반환."""
    cmd = [sys.executable, str(SCRIPTS / script)] + extra_args
    t0 = time.time()
    # 실시간 출력 (stdout/stderr 그대로 연결)
    ret = subprocess.run(cmd, cwd=str(ROOT))
    elapsed = time.time() - t0
    return ret.returncode, elapsed


def fmt_elapsed(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DB_insight 야간 점검 마스터 실행기"
    )
    parser.add_argument(
        "--only", nargs="*",
        help="실행할 단계 key만 지정 (예: calib integrity bench)"
    )
    parser.add_argument(
        "--skip-bench", action="store_true",
        help="domain_bench_queries 단계 skip (빠른 점검)"
    )
    parser.add_argument(
        "--stop-on-error", action="store_true",
        help="단계 실패 시 즉시 중단"
    )
    args = parser.parse_args()

    # 실행할 단계 필터링
    active_keys: set[str] | None = set(args.only) if args.only else None
    steps = [
        s for s in STEPS
        if (active_keys is None or s["key"] in active_keys)
        and not (args.skip_bench and s["key"] == "bench")
    ]

    start_time = datetime.datetime.now()
    print("=" * 65)
    print("  DB_insight 야간 점검 시작")
    print(f"  시작: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  단계: {[s['key'] for s in steps]}")
    print("=" * 65)

    results: list[dict] = []
    total_ok = True

    for step in steps:
        print(f"\n{'─' * 65}")
        print(f"  {step['label']}  (예상 {step['est']})")
        print(f"{'─' * 65}")

        rc, elapsed = run_step(step["script"], [])
        ok = rc == 0
        total_ok = total_ok and ok

        status = "✓ 완료" if ok else f"⚠ 경고 (exit {rc})"
        print(f"\n  → {status}  ({fmt_elapsed(elapsed)})")

        results.append({
            "key": step["key"], "script": step["script"],
            "ok": ok, "returncode": rc, "elapsed": round(elapsed, 1),
        })

        if not ok and args.stop_on_error:
            print(f"\n[stop-on-error] {step['script']} 실패 — 중단")
            break

    # 최종 요약
    end_time  = datetime.datetime.now()
    total_sec = (end_time - start_time).total_seconds()

    print(f"\n{'=' * 65}")
    print(f"  야간 점검 완료  ({fmt_elapsed(total_sec)})")
    print(f"  종료: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 65}\n")
    print(f"  {'단계':<30} {'상태':>10} {'소요':>8}")
    print(f"  {'─' * 50}")
    for r in results:
        st = "✅" if r["ok"] else "⚠️"
        print(f"  {r['script']:<30} {st:>10}  {fmt_elapsed(r['elapsed']):>8}")

    # 리포트 위치 안내
    report_dir = ROOT / "reports"
    if report_dir.exists():
        reports = sorted(report_dir.glob("inspection_*.md"), reverse=True)
        if reports:
            print(f"\n  📄 최신 리포트: {reports[0]}")

    print()
    return 0 if total_ok else 1


if __name__ == "__main__":
    sys.exit(main())
