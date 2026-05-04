"""recalibrate_image.py — L1/L2/L3 3-stage 융합 Im 기준 이미지 교차모달 재보정.

build_l1l2l3_cache.py 실행 후 Im 분포가 바뀌었으므로,
unified_engine.py 와 동일한 Im_fused 를 만들어 calibrate_image_crossmodal 재실행.

실행:
    cd App/backend
    python recalibrate_image.py
"""
import sys, io, json, logging
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from config import PATHS, TRICHEF_CFG
import numpy as np

CACHE_DIR = Path(PATHS["TRICHEF_IMG_CACHE"])

# ── 1. 캐시 파일 로드 ────────────────────────────────────────
print("=" * 60)
print("이미지 교차모달 재보정 (L1/L2/L3 3-stage 융합 기준)")
print("=" * 60)

Re  = np.load(CACHE_DIR / "cache_img_Re_siglip2.npy").astype(np.float32)
Z   = np.load(CACHE_DIR / "cache_img_Z_dinov2.npy"  ).astype(np.float32)
L1  = np.load(CACHE_DIR / "cache_img_Im_L1.npy"     ).astype(np.float32)
L2  = np.load(CACHE_DIR / "cache_img_Im_L2.npy"     ).astype(np.float32)
L3  = np.load(CACHE_DIR / "cache_img_Im_L3.npy"     ).astype(np.float32)

N = Re.shape[0]
print(f"로드 완료 — Re:{Re.shape}, Z:{Z.shape}, L1/L2/L3:{L1.shape}")

# ── 2. unified_engine.py 와 동일한 Im_fused 계산 ────────────
w1 = float(TRICHEF_CFG.get("IMG_IM_L1_ALPHA", 0.15))
w2 = float(TRICHEF_CFG.get("IMG_IM_L2_ALPHA", 0.25))
w3 = float(TRICHEF_CFG.get("IMG_IM_L3_ALPHA", 0.60))
tot = max(w1 + w2 + w3, 1e-9)
w1, w2, w3 = w1/tot, w2/tot, w3/tot

Im_fused = w1 * L1 + w2 * L2 + w3 * L3
norms = np.linalg.norm(Im_fused, axis=1, keepdims=True)
Im = Im_fused / np.maximum(norms, 1e-9)
print(f"Im_fused 계산 완료 (w=[{w1:.3f},{w2:.3f},{w3:.3f}]), shape={Im.shape}")

# ── 3. GS 직교화 ─────────────────────────────────────────────
from services.trichef import tri_gs
Im_perp, Z_perp = tri_gs.orthogonalize(Re, Im, Z)
print(f"GS 직교화 완료 — Im_perp:{Im_perp.shape}, Z_perp:{Z_perp.shape}")

# ── 4. 캡션 로드 (captions_triple.jsonl → L3 우선, 없으면 L1) ─
JSONL    = CACHE_DIR / "captions_triple.jsonl"
IDS_FILE = CACHE_DIR / "img_ids.json"

ids = json.loads(IDS_FILE.read_text("utf-8"))["ids"]
assert len(ids) == N, f"ids({len(ids)}) != Re({N})"

entries: dict[str, dict] = {}
for line in JSONL.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    try:
        obj = json.loads(line)
        entries[obj["rel"]] = obj
    except Exception:
        pass
print(f"captions_triple 항목: {len(entries)}")

captions: list[str] = []
for img_id in ids:
    obj = entries.get(img_id, {})
    # L3 (상세 묘사) 우선, 없으면 L1, 없으면 빈 문자열
    cap = (obj.get("L3") or obj.get("L1") or "").strip()
    captions.append(cap)

filled = sum(1 for c in captions if c)
print(f"캡션 보유: {filled}/{N}")

# ── 5. calibrate_image_crossmodal 실행 ───────────────────────
from services.trichef.calibration import calibrate_image_crossmodal

print("\ncalibrate_image_crossmodal 실행 중...")
result = calibrate_image_crossmodal(
    captions, Re, Im_perp, Z_perp,
    sample_q=200, pairs_per_q=5,
)

print("\n보정 결과:")
print(f"  mu_null      = {result['mu_null']:.6f}")
print(f"  sigma_null   = {result['sigma_null']:.6f}")
print(f"  abs_threshold= {result['abs_threshold']:.6f}")
print(f"  FAR          = {result.get('far', 'N/A')}")
print(f"  N            = {result.get('N', N)}")
print(f"  방법         = {result.get('method', 'crossmodal_v1')}")
print("=" * 60)
print("trichef_calibration.json 업데이트 완료.")
print("백엔드를 재시작하면 새 임계값이 적용됩니다.")
print("=" * 60)
