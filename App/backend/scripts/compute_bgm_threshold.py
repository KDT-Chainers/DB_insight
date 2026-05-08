"""scripts/compute_bgm_threshold.py — BGM 절대 임계값 산출 + calibration.json 갱신.

이미 calibration.json 에 있는 BGM irrelevant 분포 (n=2550, mu=0.109, sigma=0.147) 를
이용하여 다음을 산출:

  1. n_sigma_thresholds (n=1.0, 1.5, 2.0, 2.5, 3.0) — 다른 도메인과 동일 형식
  2. 절대 임계값 τ (FAR=0.05, 0.10, 0.20) — 정규분포 가정

산출 후 calibration.json 의 bgm.irrelevant 에 n_sigma_thresholds 필드 추가.
원본 자동 백업.

⚠️ 데이터 수집은 재실행 안 함 (기존 분포 활용). 측정 다시 하려면 별도 스크립트 필요.

사용:
  python scripts/compute_bgm_threshold.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cal_path = _BACKEND_DIR / "services" / "calibration.json"
    if not cal_path.exists():
        logger.error(f"calibration.json not found: {cal_path}")
        return

    cal = json.loads(cal_path.read_text(encoding="utf-8"))
    bgm = cal.get("bgm")
    if not bgm:
        logger.error("BGM section not found in calibration.json")
        return

    irr = bgm.get("irrelevant") or {}
    g = irr.get("gaussian") or {}
    mu = float(g.get("mu", 0.0))
    sigma = float(g.get("sigma", 0.0))
    if sigma <= 0:
        logger.error(f"Invalid sigma: {sigma}")
        return

    logger.info(f"BGM irrelevant: n={irr.get('n_samples')}, mu={mu:.4f}, sigma={sigma:.4f}")

    # n_sigma_thresholds: tau = mu + n * sigma
    n_sigma_thresholds = {}
    for n in [1.0, 1.5, 2.0, 2.5, 3.0]:
        n_sigma_thresholds[f"n_{n}"] = round(mu + n * sigma, 4)

    # FAR-based thresholds (Phi^-1)
    try:
        from scipy.stats import norm
        far_thresholds = {}
        for far in [0.01, 0.05, 0.10, 0.20]:
            z = norm.ppf(1 - far)
            far_thresholds[f"far_{far}"] = round(mu + z * sigma, 4)
    except Exception as e:
        logger.warning(f"scipy not available: {e}")
        far_thresholds = {}

    logger.info("\nn_sigma_thresholds:")
    for k, v in n_sigma_thresholds.items():
        logger.info(f"  {k}: {v}")

    logger.info("\nFAR thresholds (recommended for absolute cutoff):")
    for k, v in far_thresholds.items():
        logger.info(f"  {k}: {v}")

    logger.info("\nRecommendation:")
    logger.info(f"  FAR=0.05 (Doc/Movie/Rec parity): tau_BGM = {far_thresholds.get('far_0.05')}")
    logger.info(f"  FAR=0.20 (Image-like lenient):    tau_BGM = {far_thresholds.get('far_0.2')}")
    logger.info(f"  Current search.py floors: SIM=0.55, DENSE=0.45")

    if args.dry_run:
        logger.info("\n[DRY RUN] No changes applied.")
        return

    # Update calibration.json
    irr["n_sigma_thresholds"] = n_sigma_thresholds
    if far_thresholds:
        irr["far_thresholds"] = far_thresholds

    # Backup
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = cal_path.parent / f"calibration.bak_{ts}.json"
    shutil.copy2(cal_path, bak)
    logger.info(f"\nBackup: {bak}")

    cal_path.write_text(json.dumps(cal, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Updated: {cal_path}")
    logger.info("\nDone. BGM calibration now includes absolute thresholds.")


if __name__ == "__main__":
    main()
