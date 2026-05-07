"""Img L1/L2/L3 3-stage 캡션 임베딩 캐시 재구축.

작업:
  1. registry 의 모든 entry 의 abs 경로 → 이미지 로드
  2. BLIP-base 로 L1 (짧은 설명) / L2 (키워드) / L3 (상세 설명) 생성
  3. BGE-M3 로 각각 임베딩 → cache_img_Im_L1/L2/L3.npy 저장
  4. ids.json (2381) 순서와 정확히 일치하도록 정렬

unified_engine 의 image fusion (w_L1=0.15, w_L2=0.25, w_L3=0.60) 활성화 효과:
  → 이미지 검색 정확도 +3%~+5% 추정.

사용:
  python scripts/rebuild_img_3stage_caption.py            # 전체 재구축
  python scripts/rebuild_img_3stage_caption.py --dry-run  # 진행 미리보기
  python scripts/rebuild_img_3stage_caption.py --batch-size 16
"""
from __future__ import annotations
import argparse
import io
import json
import shutil
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
IMG_CACHE = ROOT / "Data" / "embedded_DB" / "Img"
IDS_PATH  = IMG_CACHE / "img_ids.json"
REG_PATH  = IMG_CACHE / "registry.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=16,
                        help="BGE-M3 임베딩 배치 (BLIP 캡션은 1장씩 직렬)")
    args = parser.parse_args()

    if not IDS_PATH.exists():
        print(f"[ERROR] {IDS_PATH} 없음")
        return 2

    ids_data = json.loads(IDS_PATH.read_text(encoding="utf-8"))
    ids = ids_data.get("ids", []) if isinstance(ids_data, dict) else ids_data
    n_total = len(ids)

    registry = json.loads(REG_PATH.read_text(encoding="utf-8"))
    print(f"ids.json:   {n_total}")
    print(f"registry:   {len(registry)}")

    # ids 순서대로 abs 경로 매핑
    print("\n경로 매핑 검증...")
    paths: list[Path | None] = []
    n_miss = 0
    raw_root = ROOT / "Data" / "raw_DB" / "Img"
    for i, key in enumerate(ids):
        if i % 200 == 0:
            print(f"  진행: {i}/{n_total}")
        v = registry.get(key)
        ap = None
        if isinstance(v, dict):
            cand = v.get("abs")
            if cand and Path(cand).is_file():
                ap = Path(cand)
        if ap is None:
            # staged 경로 fallback
            cand = raw_root / key
            if cand.is_file():
                ap = cand
        if ap is None:
            n_miss += 1
        paths.append(ap)
    print(f"  매핑 성공: {n_total - n_miss}, 실패: {n_miss}")

    if args.dry_run:
        print("\n(dry-run: BLIP/BGE-M3 미실행)")
        return 0

    # GPU 워밍업
    sys.path.insert(0, str(ROOT / "App" / "backend"))
    print("\nBLIP-base + BGE-M3 모델 로드 중...")
    from embedders.trichef import blip_caption_triple as blip
    from embedders.trichef import bgem3_caption_im as bge
    from PIL import Image
    import numpy as np

    L1_texts: list[str] = []
    L2_texts: list[str] = []
    L3_texts: list[str] = []
    print("\nBLIP 3-stage 캡션 생성 중 (1장씩)...")
    t0 = time.time()
    for i, p in enumerate(paths):
        if i % 50 == 0:
            elapsed = time.time() - t0
            eta = elapsed / max(i, 1) * (n_total - i)
            print(f"  {i}/{n_total}  elapsed={elapsed:.0f}s  ETA={eta:.0f}s")
        if p is None:
            L1_texts.append("")
            L2_texts.append("")
            L3_texts.append("")
            continue
        try:
            cap3 = blip.caption_triple(p)
            L1_texts.append(cap3.L1 or "")
            L2_texts.append(cap3.L2 or "")
            L3_texts.append(cap3.L3 or "")
        except Exception as e:
            L1_texts.append("")
            L2_texts.append("")
            L3_texts.append("")

    print(f"  BLIP 캡션 완료: {time.time()-t0:.0f}s")

    # BGE-M3 batch 임베딩 (각 L 채널 별)
    print("\nBGE-M3 임베딩 (L1/L2/L3)...")
    def embed_batches(texts: list[str]) -> "np.ndarray":
        out = np.zeros((n_total, 1024), dtype=np.float32)
        non_empty = [(i, t) for i, t in enumerate(texts) if t]
        for s in range(0, len(non_empty), args.batch_size):
            e = min(s + args.batch_size, len(non_empty))
            batch = [t for _, t in non_empty[s:e]]
            embs = bge.embed_passage(batch)
            for j, (idx, _) in enumerate(non_empty[s:e]):
                out[idx] = embs[j]
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-9)

    ts = int(time.time())
    for label, texts in (("L1", L1_texts), ("L2", L2_texts), ("L3", L3_texts)):
        print(f"\n  -- {label} 임베딩 --")
        arr = embed_batches(texts)
        npy_path = IMG_CACHE / f"cache_img_Im_{label}.npy"
        if npy_path.exists():
            bak = npy_path.with_suffix(npy_path.suffix + f".bak.{ts}")
            shutil.copy2(npy_path, bak)
            print(f"    백업: {bak.name}")
        np.save(npy_path, arr)
        print(f"    저장: {npy_path.name}  shape={arr.shape}")

    # 캡션 텍스트도 JSON 으로 저장 (디버깅·검증용)
    cap_json = IMG_CACHE / "caption_3stage.json"
    cap_json.write_text(
        json.dumps({"ids": ids, "L1": L1_texts, "L2": L2_texts, "L3": L3_texts},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n캡션 텍스트 저장: {cap_json.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
