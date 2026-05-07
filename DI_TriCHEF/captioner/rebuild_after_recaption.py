"""DI_TriCHEF/captioner/rebuild_after_recaption.py — Qwen 재캡션 후 후처리.

실행 순서 (이미지 unchanged, 캡션만 변경됨 가정):
  1. Im dense 재임베드 (cache_img_Im_e5cap.npy 덮어쓰기)
  2. vocab + ASF + sparse 재구축 (lexical_rebuild.rebuild_image_lexical)
  3. ChromaDB image 컬렉션 embedding 갱신 (concat 3200d upsert)
  4. Calibration 재측정 (abs_threshold 업데이트)

Re(SigLIP2) / Z(DINOv2-large) 캐시는 이미지 자체가 변하지 않았으므로 유지.

실행:
    cd DB_insight
    python DI_TriCHEF/captioner/rebuild_after_recaption.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "App" / "backend"))

from config import PATHS  # noqa: E402
from embedders.trichef import bgem3_caption_im  # noqa: E402
from embedders.trichef.caption_io import load_caption  # noqa: E402
from embedders.trichef.doc_page_render import stem_key_for  # noqa: E402
from services.trichef import calibration, lexical_rebuild, tri_gs  # noqa: E402


def _step(msg: str):
    print(f"\n{'='*70}\n[rebuild] {msg}\n{'='*70}")


def main() -> int:
    cache = Path(PATHS["TRICHEF_IMG_CACHE"])
    cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"

    ids_path = cache / "img_ids.json"
    if not ids_path.exists():
        print(f"[rebuild] ❌ {ids_path} 없음 — 중단")
        return 1
    ids = json.loads(ids_path.read_text(encoding="utf-8"))["ids"]
    print(f"[rebuild] 대상 image ids: {len(ids)}")

    # ── 1. Im dense 재임베드 ────────────────────────────────────────────
    _step("1/4 Im dense 재임베드 (BGE-M3)")
    t0 = time.time()
    # caption key = stem_key_for(id) 지만, 레거시 .txt 는 plain stem 으로도 저장됨.
    # load_caption 은 stem 인자를 그대로 받으므로, stem_key_for 우선 후 plain fallback.
    docs = []
    empty = 0
    for i in ids:
        key = stem_key_for(i)
        txt = load_caption(cap_dir, key)
        if not txt:
            # legacy plain stem fallback
            txt = load_caption(cap_dir, Path(i).stem)
        if not txt:
            empty += 1
        docs.append(txt)
    print(f"[rebuild] 캡션 로드 완료: 빈 캡션 {empty}/{len(docs)}")

    Im = bgem3_caption_im.embed_passage(docs, batch_size=32, max_length=1024)
    np.save(cache / "cache_img_Im_e5cap.npy", Im)
    print(f"[rebuild] Im 저장: {Im.shape} (elapsed {time.time()-t0:.1f}s)")

    # ── 2. Lexical 재구축 ───────────────────────────────────────────────
    _step("2/4 vocab + ASF + sparse 재구축")
    t0 = time.time()
    info = lexical_rebuild.rebuild_image_lexical()
    print(f"[rebuild] lexical 결과: {info} (elapsed {time.time()-t0:.1f}s)")

    # ── 3. ChromaDB 갱신 (생략 가능 — search 시 캐시 직접 로드) ──────────
    _step("3/4 ChromaDB image 컬렉션 upsert (concat 3200d)")
    try:
        Re = np.load(cache / "cache_img_Re_siglip2.npy").astype(np.float32)
        Z = np.load(cache / "cache_img_Z_dinov2.npy").astype(np.float32)
        if not (Re.shape[0] == Im.shape[0] == Z.shape[0] == len(ids)):
            print(f"[rebuild] ⚠️ 길이 불일치 Re={Re.shape} Im={Im.shape} Z={Z.shape} ids={len(ids)} — chroma skip")
        else:
            import chromadb
            client = chromadb.PersistentClient(path=PATHS["TRICHEF_CHROMA"])
            col = client.get_or_create_collection("trichef_image",
                                                  metadata={"hnsw:space": "cosine"})
            Im_perp, Z_perp = tri_gs.orthogonalize(Re, Im, Z)
            concat = np.concatenate([Re, Im_perp, Z_perp], axis=1).astype(np.float32)
            # cosine 공간 정규화
            norms = np.linalg.norm(concat, axis=1, keepdims=True) + 1e-12
            concat = concat / norms
            col.upsert(ids=ids, embeddings=concat.tolist())
            print(f"[rebuild] Chroma upsert {len(ids)}건 완료")
    except Exception as e:
        print(f"[rebuild] Chroma upsert 실패 (무시 가능): {type(e).__name__}: {e}")

    # ── 4. Calibration 재측정 ───────────────────────────────────────────
    _step("4/4 Calibration (abs_threshold) 재측정")
    Re = np.load(cache / "cache_img_Re_siglip2.npy").astype(np.float32)
    Z = np.load(cache / "cache_img_Z_dinov2.npy").astype(np.float32)
    Im_perp, Z_perp = tri_gs.orthogonalize(Re, Im, Z)
    calib = calibration.calibrate_domain("image", Re, Im_perp, Z_perp)
    print(f"[rebuild] calibration(image) = {calib}")

    print("\n[rebuild] ✅ 완료. 백엔드 재시작 후 검색 품질 재확인 권장.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
