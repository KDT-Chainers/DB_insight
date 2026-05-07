"""scripts/recalibrate_query_null.py — 쿼리 기반 null 분포 재보정.

기존 calibration 은 doc-doc 유사도를 null 로 사용해 query→doc 분포와
괴리가 커서 threshold 가 과도하게 높았다. 무관 랜덤 한/영 쿼리로
실제 query→doc score 분포를 샘플링하고, μ/σ 와 abs_threshold 재저장.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

from config import PATHS, TRICHEF_CFG  # noqa: E402
from services.trichef import tri_gs, calibration  # noqa: E402
from services.trichef.unified_engine import TriChefEngine  # noqa: E402


NULL_QUERIES = [
    "빨간 자동차", "파란 하늘", "생일 케이크", "강아지 산책",
    "야구 경기", "커피 한 잔", "고양이 낮잠", "바다 일몰",
    "red car", "blue sky", "birthday cake", "walking dog",
    "baseball game", "cup of coffee", "sleeping cat", "sunset beach",
    "피아노 연주", "산 정상", "눈 내리는 밤", "봄 벚꽃",
    "piano recital", "mountain peak", "snowy night", "spring blossom",
]


def recalibrate(domain: str, eng: TriChefEngine) -> dict:
    d = eng._cache[domain]
    Re, Im, Z = d["Re"], d["Im"], d["Z"]
    scores_all: list[float] = []
    for q in NULL_QUERIES:
        q_Re, q_Im = eng._embed_query_for_domain(q, domain)
        s = tri_gs.hermitian_score(
            q_Re[None, :], q_Im[None, :], q_Im[None, :], Re, Im, Z,
        )[0]
        scores_all.append(s)
    flat = np.concatenate(scores_all)
    mu, sig = float(flat.mean()), float(flat.std())

    far_key_map = {
        "image": "FAR_IMG", "doc_page": "FAR_DOC_PAGE",
        "movie": "FAR_MOVIE", "music": "FAR_MUSIC",
    }
    far_key = far_key_map.get(domain, "FAR_DOC_PAGE")
    FAR = TRICHEF_CFG.get(far_key, 0.05)
    thr = mu + calibration._acklam_inv_phi(1 - FAR) * sig

    data = calibration._load_all()
    prev = data.get(domain, {})
    data[domain] = {
        "mu_null": mu, "sigma_null": sig,
        "abs_threshold": thr, "far": FAR,
        "N": Re.shape[0], "method": "random_query_null_v2",
    }
    calibration._CALIB_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    prev_thr = prev.get("abs_threshold")
    prev_s = f"{prev_thr:.4f}" if isinstance(prev_thr, (int, float)) else "?"
    print(f"[{domain}] prev_thr={prev_s}  "
          f"→ new: μ={mu:.4f} σ={sig:.4f} thr={thr:.4f} (FAR={FAR})")
    return data[domain]


def main():
    eng = TriChefEngine()
    for dom in ["image", "doc_page", "movie", "music"]:
        if dom in eng._cache:
            recalibrate(dom, eng)


if __name__ == "__main__":
    main()
