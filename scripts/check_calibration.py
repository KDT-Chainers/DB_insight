"""scripts/check_calibration.py — 5도메인 캘리브레이션 상태 점검.

trichef_calibration.json (Doc/Image) + Bgm/calibration.json (BGM) 읽어
임계값·FAR·N·방법론 적정성을 체크하고 JSON 결과를 bench_results/ 에 저장.

실행:
  python scripts/check_calibration.py
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

DATA_DIR = ROOT / "Data" / "embedded_DB"
TRICHEF_CALIB = DATA_DIR / "trichef_calibration.json"
BGM_CALIB     = DATA_DIR / "Bgm" / "calibration.json"

# ── 적정성 기준 ──────────────────────────────────────────────────────────────
RULES: dict[str, dict] = {
    "doc_page": {
        "thr_min": 0.20, "thr_max": 0.50,
        "n_min":   100,
        "far_expected": 0.05,
        "method_preferred": "crossmodal_v1",
    },
    "image": {
        "thr_min": 0.15, "thr_max": 0.45,
        "n_min":   50,
        "far_expected": 0.20,
        "method_preferred": "crossmodal_v1",
    },
    "doc_text": {
        "thr_min": 0.20, "thr_max": 0.60,
        "n_min":   50,
        "far_expected": 0.05,
        "method_preferred": None,
    },
}

BGM_RULES = {
    "mu_expected_min":    0.35,
    "mu_expected_max":    0.55,
    "sigma_expected_min": 0.04,
    "sigma_expected_max": 0.15,
}


def _check(domain: str, d: dict) -> list[str]:
    """도메인 캘리브레이션 딕셔너리 적정성 검사. 경고 메시지 리스트 반환."""
    warnings: list[str] = []
    rule = RULES.get(domain, {})

    thr = float(d.get("abs_threshold") or 0)
    thr_min = rule.get("thr_min", 0.10)
    thr_max = rule.get("thr_max", 0.70)
    if not (thr_min <= thr <= thr_max):
        warnings.append(
            f"abs_threshold={thr:.4f} 범위 이탈 (기대 [{thr_min}, {thr_max}])"
        )

    n = int(d.get("N") or 0)
    n_min = rule.get("n_min", 10)
    if n < n_min:
        warnings.append(f"N={n} < 최소 {n_min} — 캘리브레이션 신뢰성 낮음")

    far = float(d.get("far") or 0)
    far_exp = rule.get("far_expected")
    if far_exp is not None and abs(far - far_exp) > 0.001:
        warnings.append(f"FAR={far} ≠ 기대값 {far_exp}")

    method = d.get("method", "self_pair")
    pref = rule.get("method_preferred")
    if pref and method != pref:
        warnings.append(
            f"method='{method}' (권장: '{pref}') — crossmodal calibration 재실행 권장"
        )

    sig = float(d.get("sigma_null") or 0)
    if sig < 1e-4:
        warnings.append(f"sigma_null={sig:.6f} 너무 작음 — 분포 붕괴 의심")

    return warnings


def main() -> int:
    report: dict = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "trichef": {},
        "bgm": {},
        "summary": {"ok": 0, "warn": 0, "missing": 0},
    }

    print("=" * 60)
    print("  DB_insight 캘리브레이션 점검")
    print("=" * 60)

    # ── Tri-CHEF 캘리브레이션 (Doc / Image) ──────────────────────────────────
    print(f"\n[1] trichef_calibration.json: {TRICHEF_CALIB}")
    if not TRICHEF_CALIB.exists():
        print("  ⚠ 파일 없음 — 캘리브레이션 미실행 상태")
        report["trichef"]["_error"] = "파일 없음"
        report["summary"]["missing"] += 1
    else:
        data: dict = json.loads(TRICHEF_CALIB.read_text(encoding="utf-8-sig"))
        for domain, d in data.items():
            thr   = d.get("abs_threshold", 0)
            mu    = d.get("mu_null", 0)
            sig   = d.get("sigma_null", 0)
            n     = d.get("N", 0)
            far   = d.get("far", "?")
            meth  = d.get("method", "self_pair")
            warns = _check(domain, d)

            status = "✓" if not warns else "⚠"
            print(f"\n  [{status}] {domain}")
            print(f"       mu={mu:.4f}  sigma={sig:.4f}  thr={thr:.4f}  FAR={far}  N={n}  method={meth}")
            for w in warns:
                print(f"       ⚠ {w}")

            report["trichef"][domain] = {
                "abs_threshold": thr, "mu_null": mu, "sigma_null": sig,
                "N": n, "far": far, "method": meth,
                "warnings": warns, "ok": not warns,
            }
            if warns:
                report["summary"]["warn"] += 1
            else:
                report["summary"]["ok"] += 1

    # ── BGM 캘리브레이션 ──────────────────────────────────────────────────────
    print(f"\n[2] BGM calibration.json: {BGM_CALIB}")
    if not BGM_CALIB.exists():
        print("  ⚠ 파일 없음 — 기본값 mu=0.40 sigma=0.08 사용 중")
        print("     → scripts/bgm_calibrate.py 실행 권장")
        report["bgm"] = {"_error": "파일 없음 (기본값 사용 중)", "warnings": ["calibration.json 없음"]}
        report["summary"]["missing"] += 1
    else:
        bgm = json.loads(BGM_CALIB.read_text(encoding="utf-8-sig"))
        mu  = float(bgm.get("mu_null", 0.40))
        sig = float(bgm.get("sigma_null", 0.08))
        n   = bgm.get("N", "?")

        bgm_warns: list[str] = []
        r = BGM_RULES
        if not (r["mu_expected_min"] <= mu <= r["mu_expected_max"]):
            bgm_warns.append(f"mu_null={mu:.4f} 기대 범위 [{r['mu_expected_min']}, {r['mu_expected_max']}] 이탈")
        if not (r["sigma_expected_min"] <= sig <= r["sigma_expected_max"]):
            bgm_warns.append(f"sigma_null={sig:.4f} 기대 범위 [{r['sigma_expected_min']}, {r['sigma_expected_max']}] 이탈")

        status = "✓" if not bgm_warns else "⚠"
        print(f"  [{status}] BGM: mu={mu:.4f}  sigma={sig:.4f}  N={n}")
        for w in bgm_warns:
            print(f"       ⚠ {w}")

        report["bgm"] = {"mu_null": mu, "sigma_null": sig, "N": n,
                         "warnings": bgm_warns, "ok": not bgm_warns}
        if bgm_warns:
            report["summary"]["warn"] += 1
        else:
            report["summary"]["ok"] += 1

    # ── 추가: DOC_IM_ALPHA 현재값 알림 ───────────────────────────────────────
    print("\n[3] DOC_IM_ALPHA 현재 설정")
    try:
        from config import TRICHEF_CFG
        alpha = TRICHEF_CFG.get("DOC_IM_ALPHA", "?")
        status = "✓" if alpha <= 0.20 else "⚠"
        print(f"  [{status}] DOC_IM_ALPHA = {alpha}")
        if alpha > 0.20:
            print("     ⚠ 권장값 0.20 (현재 {alpha}) — tune_doc_im_alpha.py 참고")
        report["doc_im_alpha"] = {"current": alpha, "recommended": 0.20,
                                   "ok": alpha <= 0.20}
    except Exception as e:
        print(f"  ⚠ config 로드 실패: {e}")

    # ── 요약 ──────────────────────────────────────────────────────────────────
    s = report["summary"]
    print(f"\n{'=' * 60}")
    print(f"결과: ✓ OK={s['ok']}  ⚠ WARN={s['warn']}  ✗ MISSING={s['missing']}")
    print(f"{'=' * 60}")

    out_dir = ROOT / "bench_results"
    out_dir.mkdir(exist_ok=True)
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"{ts}_check_calibration.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[saved] {out}")
    return 0 if s["warn"] == 0 and s["missing"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
