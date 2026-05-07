"""Img 잉여 캐시 정리 — 사용 안 되는 .npy 파일 백업.

대상:
  - cache_img_Im.npy (메인은 cache_img_Im_e5cap.npy 사용, 이건 잉여)
  - cache_img_Im_L1/L2/L3.npy (3-stage fusion, 행수 mismatch 로 비활성)

처리:
  .bak.<timestamp> 로 이름 변경. 검색 작동 영향 없음.
  3-stage fusion 재활성화 원할 시 이슈 2-B (rebuild_img_3stage_caption.py) 실행.
"""
from __future__ import annotations
import io, sys, time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
IMG_CACHE = ROOT / "Data" / "embedded_DB" / "Img"

ORPHAN_FILES = [
    "cache_img_Im.npy",
    "cache_img_Im_L1.npy",
    "cache_img_Im_L2.npy",
    "cache_img_Im_L3.npy",
]

ts = int(time.time())
moved = 0
for fn in ORPHAN_FILES:
    p = IMG_CACHE / fn
    if not p.exists():
        print(f"  - {fn}: 없음 (skip)")
        continue
    bak = p.with_suffix(p.suffix + f".bak.{ts}")
    p.rename(bak)
    print(f"  + {fn} -> {bak.name}")
    moved += 1

print(f"\n총 {moved} 파일 백업 완료. 검색 작동 동일.")
