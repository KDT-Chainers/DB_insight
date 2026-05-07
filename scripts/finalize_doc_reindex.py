"""scripts/finalize_doc_reindex.py — .npy 기반 ChromaDB upsert + registry 저장 복구.

ChromaDB batch size 초과로 중단된 상태에서 .npy/ids.json 은 온전. 재임베딩 없이
Gram-Schmidt + chunked upsert + calibration + registry 저장만 수행.
"""
from __future__ import annotations

import hashlib
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
from embedders.trichef.incremental_runner import _upsert_chroma  # noqa: E402


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    cache = Path(PATHS["TRICHEF_DOC_CACHE"])
    raw   = Path(PATHS["RAW_DB"]) / "Doc"
    extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])

    Re = np.load(cache / "cache_doc_page_Re.npy")
    Im = np.load(cache / "cache_doc_page_Im.npy")
    Z  = np.load(cache / "cache_doc_page_Z.npy")
    ids = json.loads((cache / "doc_page_ids.json").read_text(encoding="utf-8"))["ids"]
    print(f"Re {Re.shape}, Im {Im.shape}, Z {Z.shape}, ids {len(ids)}")

    Im_perp, Z_perp = tri_gs.orthogonalize(Re, Im, Z)
    print("Gram-Schmidt OK")

    _upsert_chroma(TRICHEF_CFG["COL_DOC_PAGE"], ids, Re, Im_perp, Z_perp, extract)
    print("ChromaDB upsert OK")

    calibration.calibrate_domain("doc_page", Re, Im_perp, Z_perp)
    print("calibration OK")

    reg_path = cache / "registry.json"
    registry: dict = {}
    exts = {".pdf", ".docx", ".hwp", ".xlsx", ".txt"}
    for p in raw.rglob("*"):
        if p.is_file() and p.suffix.lower() == ".pdf":
            try:
                if p.stat().st_size == 0:
                    continue
                key = str(p.relative_to(raw)).replace("\\", "/")
                registry[key] = {"sha": _sha256(p), "abs": str(p)}
            except OSError:
                continue
    reg_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"registry saved: {len(registry)}")


if __name__ == "__main__":
    main()
