"""DI_TriCHEF/auto_calibration/auto_recalibrate.py

새 데이터 추가 시 abs_threshold 자동 재보정 트리거.

호출 지점(권장): incremental_runner.run_doc_incremental / run_img_incremental 말미.

트리거 조건 (OR):
  1) 추가/수정 비율 ≥ 10%         : added / max(total, 1) >= 0.10
  2) 절대 증가량 ≥ 500            : (total - last_calibrated_N) >= 500
  3) 초기 상태 N < 100            : 부트스트랩

메타데이터: `last_calibrated_N` 를 domain meta 에 기록하여 중복 재캘리 방지.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

RATIO_THRESHOLD = 0.10
ABS_DELTA_THRESHOLD = 500
BOOTSTRAP_N = 100


def should_recalibrate(added: int, total: int, last_calibrated_N: int) -> tuple[bool, str]:
    if total < BOOTSTRAP_N:
        return True, f"bootstrap (N={total} < {BOOTSTRAP_N})"
    if total - last_calibrated_N >= ABS_DELTA_THRESHOLD:
        return True, f"abs-delta {total - last_calibrated_N} >= {ABS_DELTA_THRESHOLD}"
    if added / max(total, 1) >= RATIO_THRESHOLD:
        return True, f"ratio {added/max(total,1):.2%} >= {RATIO_THRESHOLD:.0%}"
    return False, "no-op"


def maybe_recalibrate(
    domain: str,
    Re: np.ndarray,
    Im_perp: np.ndarray,
    Z_perp: np.ndarray,
    added: int,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """조건 충족 시 `services.trichef.calibration.calibrate_domain` 호출.

    meta dict 를 in-place 업데이트 (`last_calibrated_N`). 호출측은 meta 저장 책임.
    """
    from services.trichef import calibration

    total = int(Re.shape[0])
    last = int(meta.get("last_calibrated_N", 0))
    do, reason = should_recalibrate(added, total, last)
    if not do:
        logger.info(f"[auto-calib:{domain}] skip — {reason} (N={total}, last={last})")
        return meta

    logger.info(f"[auto-calib:{domain}] RUN — {reason} (N={total}, last={last})")
    result = calibration.calibrate_domain(domain, Re, Im_perp, Z_perp)
    meta["last_calibrated_N"] = total
    meta["last_calibration_reason"] = reason
    meta["last_calibration_result"] = {
        k: result.get(k) for k in ("mu_null", "sigma_null", "abs_threshold", "far")
    }
    return meta
