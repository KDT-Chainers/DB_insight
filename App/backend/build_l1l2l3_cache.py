"""build_l1l2l3_cache.py — L1/L2/L3 캡션 수준별 BGE-M3 Im 캐시 구축.

unified_engine.py 가 cache_img_Im_L1/L2/L3.npy 를 발견하면
  Im_fused = 0.15*L1 + 0.25*L2 + 0.60*L3  (renormalize)
로 3-stage fusion 을 활성화합니다.

현재 shape mismatch 경고가 발생하는 이유: L1/L2/L3 npy 가 없어서 스킵됨.
이 스크립트 실행 후 백엔드 재시작하면 3-stage fusion 활성화됩니다.

실행:
    python build_l1l2l3_cache.py
"""
import sys, io, json, logging
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))
from config import PATHS

import numpy as np

CACHE_DIR = Path(PATHS["TRICHEF_IMG_CACHE"])
JSONL     = CACHE_DIR / "captions_triple.jsonl"
IDS_FILE  = CACHE_DIR / "img_ids.json"
IM_BASE   = CACHE_DIR / "cache_img_Im_e5cap.npy"  # fallback 원본

OUT_L1 = CACHE_DIR / "cache_img_Im_L1.npy"
OUT_L2 = CACHE_DIR / "cache_img_Im_L2.npy"
OUT_L3 = CACHE_DIR / "cache_img_Im_L3.npy"

BATCH = 64


def main():
    print("=" * 60)
    print("L1/L2/L3 3-stage Im 캐시 구축 시작")
    print("=" * 60)

    # ── 1. captions_triple.jsonl 로드 ─────────────────────────────
    if not JSONL.exists():
        print(f"ERROR: captions_triple.jsonl 없음: {JSONL}")
        return

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

    # ── 2. img_ids.json 순서대로 L1/L2/L3 리스트 구성 ────────────
    ids = json.loads(IDS_FILE.read_text("utf-8"))["ids"]
    N = len(ids)
    print(f"img_ids: {N}")

    # 원본 Im 로드 (빈 캡션 fallback 용)
    Im_base = np.load(IM_BASE).astype(np.float32)  # (N, 1024)
    assert Im_base.shape[0] == N, f"Im_base 행 수 불일치: {Im_base.shape[0]} vs {N}"

    l1_texts: list[str] = []
    l2_texts: list[str] = []
    l3_texts: list[str] = []
    fallback_mask: list[bool] = []

    for img_id in ids:
        obj = entries.get(img_id, {})
        l1 = (obj.get("L1") or "").strip()
        l2 = (obj.get("L2") or "").strip()
        l3 = (obj.get("L3") or "").strip()
        # L3 없으면 L1 fallback (최소한 주제는 유지)
        if not l3:
            l3 = l1
        # L1 없으면 L3 앞 50자 fallback
        if not l1:
            l1 = l3[:50]
        # L2 없으면 L1 fallback
        if not l2:
            l2 = l1

        l1_texts.append(l1 if l1 else "사진")
        l2_texts.append(l2 if l2 else "사진")
        l3_texts.append(l3 if l3 else "사진")
        fallback_mask.append(not (l1 or l3))

    empty_count = sum(fallback_mask)
    print(f"  완전 빈 항목 (fallback='사진'): {empty_count}")

    # ── 3. BGE-M3 embed_passage ────────────────────────────────────
    from embedders.trichef import bgem3_caption_im as im_embedder

    print("[1/3] L1 임베딩 중...")
    L1_mat = im_embedder.embed_passage(l1_texts)  # (N, 1024)
    print(f"  L1 shape: {L1_mat.shape}")

    print("[2/3] L2 임베딩 중...")
    L2_mat = im_embedder.embed_passage(l2_texts)
    print(f"  L2 shape: {L2_mat.shape}")

    print("[3/3] L3 임베딩 중...")
    L3_mat = im_embedder.embed_passage(l3_texts)
    print(f"  L3 shape: {L3_mat.shape}")

    # ── 4. 완전 빈 항목은 Im_base 로 교체 ─────────────────────────
    if empty_count > 0:
        for i, is_fallback in enumerate(fallback_mask):
            if is_fallback:
                L1_mat[i] = Im_base[i]
                L2_mat[i] = Im_base[i]
                L3_mat[i] = Im_base[i]

    # ── 5. 저장 ───────────────────────────────────────────────────
    np.save(OUT_L1, L1_mat.astype(np.float32))
    np.save(OUT_L2, L2_mat.astype(np.float32))
    np.save(OUT_L3, L3_mat.astype(np.float32))

    print(f"\n저장 완료:")
    print(f"  {OUT_L1}")
    print(f"  {OUT_L2}")
    print(f"  {OUT_L3}")
    print("\n백엔드를 재시작하면 3-stage fusion 이 활성화됩니다.")
    print("  w_L1=0.15 (주제), w_L2=0.25 (키워드), w_L3=0.60 (상세)")
    print("=" * 60)


if __name__ == "__main__":
    main()
