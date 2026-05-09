"""scripts/diag_doc_scores.py — doc_page 점수 분포 진단"""
import sys, json
import numpy as np
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from config import PATHS, TRICHEF_CFG
from services.trichef import tri_gs

ddir = __import__("pathlib").Path(PATHS["TRICHEF_DOC_CACHE"])
Re     = np.load(ddir / "cache_doc_page_Re.npy").astype(np.float32)
Im_raw = np.load(ddir / "cache_doc_page_Im.npy").astype(np.float32)
Z      = np.load(ddir / "cache_doc_page_Z.npy").astype(np.float32)
ids    = json.loads((ddir / "doc_page_ids.json").read_text(encoding="utf-8"))["ids"]

body_path = ddir / "cache_doc_page_Im_body.npy"
if body_path.exists():
    Im_body = np.load(body_path).astype(np.float32)
    if Im_body.shape == Im_raw.shape:
        _a = float(TRICHEF_CFG.get("DOC_IM_ALPHA", 0.35))
        Im_fused = _a * Im_raw + (1.0 - _a) * Im_body
        norms = np.linalg.norm(Im_fused, axis=1, keepdims=True)
        Im = Im_fused / np.maximum(norms, 1e-9)
        print(f"Im_body fusion: DOC_IM_ALPHA={_a}, shape={Im.shape}")
    else:
        Im = Im_raw
        print(f"Im_body shape mismatch: {Im_body.shape} vs {Im_raw.shape}")
else:
    Im = Im_raw
    print("Im_body 없음 — Im_raw 사용")

print(f"N pages: {len(ids)}")

from embedders.trichef import siglip2_re, bgem3_caption_im as e5
query = "글로벌 XR 활용 최신 동향 및 시사점"
q_Re = siglip2_re.embed_texts([query])
q_Re = q_Re / (np.linalg.norm(q_Re, axis=1, keepdims=True) + 1e-12)
q_Im = e5.embed_query([query])
q_Im = q_Im / (np.linalg.norm(q_Im, axis=1, keepdims=True) + 1e-12)
q_Z  = np.zeros_like(q_Im)

scores_08 = tri_gs.hermitian_score(q_Re, q_Im, q_Z, Re, Im, Z, alpha=0.8)[0]
scores_04 = tri_gs.hermitian_score(q_Re, q_Im, q_Z, Re, Im, Z, alpha=0.4)[0]

THR = 0.27177

print(f"\n=== alpha=0.8 점수 분포 ===")
print(f"  min={scores_08.min():.4f}  max={scores_08.max():.4f}")
print(f"  mean={scores_08.mean():.4f}  std={scores_08.std():.4f}")
print(f"  p90={np.percentile(scores_08,90):.4f}  p95={np.percentile(scores_08,95):.4f}  p99={np.percentile(scores_08,99):.4f}")
print(f"  threshold={THR} 초과: {(scores_08 > THR).sum()}개")

print(f"\n=== alpha=0.4 점수 분포 ===")
print(f"  min={scores_04.min():.4f}  max={scores_04.max():.4f}")
print(f"  mean={scores_04.mean():.4f}  std={scores_04.std():.4f}")
print(f"  threshold={THR} 초과: {(scores_04 > THR).sum()}개")

print(f"\n=== Top-20 (alpha=0.8) ===")
order = np.argsort(-scores_08)
for rank, i in enumerate(order[:20]):
    print(f"  #{rank+1:2d} {scores_08[i]:.4f}  {ids[i]}")

print(f"\n=== XR/SW/10월 관련 문서 점수 ===")
keywords = ["XR", "VR", "AR", "SW중심", "SW_중심", "10월", "글로벌"]
found = False
for i, doc_id in enumerate(ids):
    if any(kw in doc_id for kw in keywords):
        print(f"  [{i:5d}] 0.8={scores_08[i]:.4f}  0.4={scores_04[i]:.4f}  {doc_id}")
        found = True
if not found:
    print("  (키워드 매칭 없음 — 파일명 샘플 출력)")
    for i, doc_id in enumerate(ids[:5]):
        print(f"  sample: {doc_id}")
