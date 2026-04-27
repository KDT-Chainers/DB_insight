"""Movie Re/segments/ids 정합성 점검."""
import json
import numpy as np
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
d = _ROOT / "Data" / "embedded_DB" / "Movie"
Re = np.load(d / "cache_movie_Re.npy", mmap_mode="r")
segs = json.load(open(d / "segments.json", encoding="utf-8"))
ids_raw = json.load(open(d / "movie_ids.json", encoding="utf-8"))
ids = ids_raw.get("ids", ids_raw) if isinstance(ids_raw, dict) else ids_raw

print(f"Re shape:  {Re.shape}")
print(f"segments:  {len(segs)}")
print(f"ids:       {len(ids)}")
print()
if len(segs) != Re.shape[0]:
    delta = len(segs) - Re.shape[0]
    print(f"[MISMATCH] segments - Re = {delta}")
