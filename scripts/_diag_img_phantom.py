"""Img cache의 9개 phantom 파일(매번 신규로 잡히는) 식별.

cache_img_Im.npy = 2390 행 vs registry = 2381 entries → 9 phantom 행 존재.
또한 raw_DB/Img 디스크 파일 중 registry 의 abs 와 매칭 안 되는 파일 식별.
"""
import sys, io, json
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "Data" / "raw_DB" / "Img"
EMB = ROOT / "Data" / "embedded_DB" / "Img"

reg = json.loads((EMB / "registry.json").read_text(encoding="utf-8"))
ids = json.loads((EMB / "img_ids.json").read_text(encoding="utf-8"))
ids_list = ids.get("ids", []) if isinstance(ids, dict) else ids

# registry abs paths (정규화)
reg_abs = set()
for k, v in reg.items():
    if isinstance(v, dict):
        ap = v.get("abs")
        if ap:
            reg_abs.add(str(Path(ap).resolve()).lower().replace("\\", "/"))

# 디스크 모든 이미지
disk_files = []
for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG", "*.png", "*.PNG", "*.gif"):
    for sub in RAW.iterdir():
        if not sub.is_dir() or sub.name == "staged":
            continue
        for p in sub.rglob(ext):
            disk_files.append(p)

# unique
disk_set = set(str(p.resolve()).lower().replace("\\", "/") for p in disk_files)
print(f"디스크 Img 파일 (staged 제외): {len(disk_set)}")
print(f"registry abs 등록:              {len(reg_abs)}")
print(f"registry total entries:         {len(reg)}")

# disk 에 있지만 registry abs 에 없는
phantom = disk_set - reg_abs
print(f"\nPhantom (디스크 있음, registry 없음): {len(phantom)}")
for p in list(phantom)[:15]:
    # SHA 같은 파일이 registry 에 다른 형식으로 있는지
    print(f"  {p}")

# .npy vs registry 비교 — ids_list 의 어떤 항목이 registry 에 없는지
not_in_reg = [i for i in ids_list if i not in reg]
print(f"\nids.json 의 항목 중 registry 에 없는 것: {len(not_in_reg)}")
for i in not_in_reg[:15]:
    print(f"  {i}")
