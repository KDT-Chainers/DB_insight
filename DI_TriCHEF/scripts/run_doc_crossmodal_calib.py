"""run_doc_crossmodal_calib.py — 기존 doc_page 캐시로 W5-3 calibration 즉시 실행.

Reindex 를 기다리지 않고 현재 상태의 Re/Im/Z + 캡션을 읽어 cross-modal null 분포 측정.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "App" / "backend"))

from config import PATHS
from embedders.trichef.caption_io import load_caption
from services.trichef import calibration, tri_gs


def main() -> None:
    cache = Path(PATHS["TRICHEF_DOC_CACHE"])
    extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])
    cap_root = extract / "captions"

    Re = np.load(cache / "cache_doc_page_Re.npy")
    Im = np.load(cache / "cache_doc_page_Im.npy")
    Z  = np.load(cache / "cache_doc_page_Z.npy")
    ids = json.loads((cache / "doc_page_ids.json").read_text(encoding="utf-8"))["ids"]
    print(f"loaded Re={Re.shape} Im={Im.shape} Z={Z.shape} ids={len(ids)}")

    Im_perp, Z_perp = tri_gs.orthogonalize(Re, Im, Z)
    print(f"orthogonalized")

    caps: list[str] = []
    for did in ids:
        parts = Path(did).parts
        if len(parts) >= 3 and parts[0] == "page_images":
            stem = parts[1]
            page_stem = Path(parts[2]).stem
            t = load_caption(cap_root / stem, page_stem) or ""
        else:
            t = ""
        caps.append(t)
    non_empty = sum(1 for c in caps if c.strip())
    print(f"captions loaded: {non_empty}/{len(caps)} non-empty")

    before = calibration.get_thresholds("doc_page")
    print(f"BEFORE: {json.dumps(before, indent=2)}")

    info = calibration.calibrate_crossmodal(
        "doc_page", caps, Re, Im_perp, Z_perp,
        sample_q=200, pairs_per_q=5,
    )
    print(f"AFTER:  {json.dumps(info, indent=2)}")


if __name__ == "__main__":
    main()
