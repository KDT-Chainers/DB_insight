"""검색 fusion 채널 활성화 검증 — Doc Im_body / Img L1/L2/L3 / sparse / ASF.

unified_engine 의 _build_entry 가 cache 파일 shape mismatch 시 fusion 자동 비활성.
이 스크립트는 cache 정합성 + fusion 활성 여부를 한 번에 보고.
"""
from __future__ import annotations
import sys
import json
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("=" * 70)
print("검색 fusion 채널 활성화 검증")
print("=" * 70)

ROOT = Path(__file__).resolve().parents[1]
EMB = ROOT / "Data" / "embedded_DB"

import numpy as np


def shape_or_missing(p: Path):
    if not p.exists():
        return None
    try:
        arr = np.load(p, mmap_mode="r")
        return arr.shape
    except Exception as e:
        return f"ERR:{e}"


# ── Img: L1/L2/L3 3-stage caption fusion ──────────────────────────
print("\n[Img] 3-stage caption fusion (L1/L2/L3)")
img_dir = EMB / "Img"
im_main = shape_or_missing(img_dir / "cache_img_Im_e5cap.npy")
L1 = shape_or_missing(img_dir / "cache_img_Im_L1.npy")
L2 = shape_or_missing(img_dir / "cache_img_Im_L2.npy")
L3 = shape_or_missing(img_dir / "cache_img_Im_L3.npy")
print(f"  cache_img_Im_e5cap.npy: {im_main}")
print(f"  cache_img_Im_L1.npy:    {L1}")
print(f"  cache_img_Im_L2.npy:    {L2}")
print(f"  cache_img_Im_L3.npy:    {L3}")
if im_main and L1 and L2 and L3 and im_main == L1 == L2 == L3:
    print(f"  → ✅ 3-stage fusion 활성 (w_L1=0.15, w_L2=0.25, w_L3=0.60)")
else:
    print(f"  → ⚠️ 3-stage fusion 비활성 (shape 미스매치 또는 파일 없음)")

# ── Doc: Im_body fusion ───────────────────────────────────────────
print("\n[Doc] Im_body fusion (캡션 + 본문 가중 합)")
doc_dir = EMB / "Doc"
im_doc = shape_or_missing(doc_dir / "cache_doc_page_Im.npy")
im_body = shape_or_missing(doc_dir / "cache_doc_page_Im_body.npy")
print(f"  cache_doc_page_Im.npy:      {im_doc}")
print(f"  cache_doc_page_Im_body.npy: {im_body}")
if im_doc and im_body and im_doc == im_body:
    print(f"  → ✅ Im_body fusion 활성 (α=0.35: 캡션 35% + 본문 65%)")
else:
    print(f"  → ⚠️ Im_body fusion 비활성 — 본문 채널 미사용")

# ── Sparse lexical (Doc/Movie/Rec) ────────────────────────────────
print("\n[Sparse Lexical 채널]")
for dom_label, dom_dir in (("Doc", doc_dir), ("Img", img_dir)):
    sparse = dom_dir / "cache_img_sparse.npz" if dom_label == "Img" else \
             dom_dir / "cache_doc_page_sparse.npz"
    if sparse.exists():
        print(f"  {dom_label}: sparse 캐시 있음 ({sparse.name})")
    else:
        print(f"  {dom_label}: sparse 캐시 없음 ({sparse.name})")

# ── ASF token_sets ────────────────────────────────────────────────
print("\n[ASF Lexical 채널 — vocab + token_sets]")
for dom in ("Doc", "Img", "Movie", "Rec"):
    d = EMB / dom
    vocab_files = list(d.glob("*vocab*.json"))
    ts_files = list(d.glob("*token_sets*.json"))
    if not vocab_files or not ts_files:
        print(f"  {dom}: ⚠️ vocab 또는 token_sets 없음")
        continue
    try:
        v = json.loads(vocab_files[0].read_text(encoding="utf-8"))
        ts = json.loads(ts_files[0].read_text(encoding="utf-8"))
        n_v = len(v) if isinstance(v, dict) else 0
        n_ts = len(ts) if isinstance(ts, list) else 0
        names = [vocab_files[0].name, ts_files[0].name]
        print(f"  {dom}: vocab={n_v} token_sets={n_ts}  ({', '.join(names)})")
        # 인명 검증
        if isinstance(v, dict):
            checks = []
            for term in ("박태웅", "의장", "korean"):
                if term in v:
                    checks.append(f"{term}✓")
            if checks:
                print(f"    포함: {', '.join(checks)}")
    except Exception as e:
        print(f"  {dom}: 로드 실패 — {e}")

print("\n" + "=" * 70)
print("결론: 위에 ✅ 가 많을수록 검색 정확도 강화 채널 활성")
print("=" * 70)
