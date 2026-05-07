"""rebuild_im_cache_all.py — Doc + Image Im 임베딩 캐시 재빌드 (BGE-M3).

Step D 실행 스크립트. gen_doc_summaries_gemma.py 와 merge_img_stage_captions.py
완료 후 실행.

Doc:
  Data/extracted_DB/Doc/captions/**/*.caption.json → BGE-M3 encode
  → Data/embedded_DB/Doc/cache_doc_page_Im.npy  (덮어쓰기, bak 백업)

Image:
  Data/embedded_DB/Img/captions_triple.jsonl (L1/L2/L3) → BGE-M3 encode
  → cache_img_Im_L1.npy / L2.npy / L3.npy  (덮어쓰기, bak 백업)

BGE-M3 이미 cross-lingual 지원 (한·영 정렬)
  → 캡션만 한국어로 고치면 크로스링구얼 자동 개선

사용:
  cd App/backend && python scripts/rebuild_im_cache_all.py
  cd App/backend && python scripts/rebuild_im_cache_all.py --doc-only
  cd App/backend && python scripts/rebuild_im_cache_all.py --img-only
"""
from __future__ import annotations
import sys, json, argparse, time, shutil
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # App/backend

ROOT        = Path(__file__).resolve().parents[3]
DOC_CACHE   = ROOT / "Data" / "embedded_DB" / "Doc"
IMG_CACHE   = ROOT / "Data" / "embedded_DB" / "Img"
DOC_CAP_DIR = ROOT / "Data" / "extracted_DB" / "Doc" / "captions"
JSONL_PATH  = IMG_CACHE / "captions_triple.jsonl"
DOC_IDS     = DOC_CACHE / "doc_page_ids.json"
IMG_IDS     = IMG_CACHE / "img_ids.json"

BATCH_SIZE  = 64   # BGE-M3 RTX 4070 8GB 최적


def _load_bgem3():
    """BGE-M3 로드 (FlagEmbedding)."""
    from FlagEmbedding import BGEM3FlagModel
    print("[bgem3] 모델 로드 중 (BAAI/bge-m3)...", flush=True)
    model = BGEM3FlagModel(
        "BAAI/bge-m3",
        use_fp16=True,
        devices=["cuda"],
    )
    print("[bgem3] 로드 완료", flush=True)
    return model


def _encode(model, texts: list[str], desc: str = "") -> np.ndarray:
    """BGE-M3 dense encode → (N, 1024) float32."""
    print(f"  [{desc}] {len(texts)}건 인코딩...", flush=True)
    t0 = time.time()
    out = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        max_length=512,
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )
    vecs = np.asarray(out["dense_vecs"], dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12
    vecs = vecs / norms
    elapsed = time.time() - t0
    print(f"  [{desc}] 완료: shape={vecs.shape} ({elapsed:.1f}s)", flush=True)
    return vecs


def _backup(path: Path) -> None:
    if path.exists():
        bak = path.with_suffix(path.suffix + ".bak_before_rebuild")
        shutil.copy2(path, bak)
        print(f"  백업: {bak.name}", flush=True)


def rebuild_doc(model) -> bool:
    """Doc Im 캐시 재빌드."""
    print("\n━━━ Doc Im 캐시 재빌드 ━━━", flush=True)
    t0 = time.time()

    ids_raw = json.loads(DOC_IDS.read_text(encoding="utf-8"))
    ids = ids_raw.get("ids", ids_raw) if isinstance(ids_raw, dict) else ids_raw
    print(f"  페이지 수: {len(ids)}", flush=True)

    # 각 페이지 캡션 텍스트 로드 (새 .caption.json 우선, fallback .txt)
    texts: list[str] = []
    cap_ok = cap_fallback = cap_empty = 0

    for page_id in ids:
        parts = Path(page_id).parts
        doc_folder = parts[1] if (len(parts) >= 3 and parts[0] == "page_images") else parts[0] if len(parts) >= 2 else ""
        stem = Path(parts[-1]).stem if parts else "p0000"

        cap_json = DOC_CAP_DIR / doc_folder / f"{stem}.caption.json"
        cap_txt  = DOC_CAP_DIR / doc_folder / f"{stem}.txt"

        text = ""
        if cap_json.exists():
            try:
                d = json.loads(cap_json.read_text(encoding="utf-8"))
                parts_text = [d.get(k, "") for k in ("L1", "L2", "L3")]
                text = " ".join(x for x in parts_text if x).strip()
                if text:
                    cap_ok += 1
            except Exception:
                pass
        if not text and cap_txt.exists():
            try:
                text = cap_txt.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    cap_fallback += 1
            except Exception:
                pass
        if not text:
            cap_empty += 1
            text = Path(page_id).parts[1] if len(Path(page_id).parts) >= 2 else "문서"

        texts.append(f"passage: {text}")

    print(f"  캡션 로드: JSON={cap_ok} / txt fallback={cap_fallback} / 빈칸={cap_empty}", flush=True)

    # BGE-M3 인코딩
    vecs = _encode(model, texts, "Doc Im")

    # 저장
    out_path = DOC_CACHE / "cache_doc_page_Im.npy"
    _backup(out_path)
    np.save(out_path, vecs)
    print(f"  저장: {out_path} shape={vecs.shape}", flush=True)
    print(f"  Doc Im 재빌드 완료 ({(time.time()-t0)/60:.1f}분)", flush=True)
    return True


def rebuild_img(model) -> bool:
    """Image Im L1/L2/L3 캐시 재빌드."""
    print("\n━━━ Image Im 캐시 재빌드 ━━━", flush=True)
    t0 = time.time()

    if not JSONL_PATH.exists():
        print("  [오류] captions_triple.jsonl 없음", flush=True)
        return False

    ids_raw = json.loads(IMG_IDS.read_text(encoding="utf-8"))
    ids = ids_raw.get("ids", ids_raw) if isinstance(ids_raw, dict) else ids_raw
    print(f"  이미지 수: {len(ids)}", flush=True)

    # JSONL → {key: {L1,L2,L3}}
    caption_map: dict[str, dict] = {}
    with JSONL_PATH.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                key = d.get("key") or d.get("id", "")
                if key:
                    caption_map[key] = d
            except Exception:
                continue
    print(f"  JSONL 로드: {len(caption_map)}건", flush=True)

    texts_l1: list[str] = []
    texts_l2: list[str] = []
    texts_l3: list[str] = []
    missing = 0

    for key in ids:
        d = caption_map.get(key, {})
        l1 = d.get("L1", "") or ""
        l2 = d.get("L2", "") or ""
        l3 = d.get("L3", "") or ""
        if not (l1 or l2 or l3):
            missing += 1
        texts_l1.append(f"passage: {l1}" if l1 else "passage: image")
        texts_l2.append(f"passage: {l2}" if l2 else "passage: image")
        texts_l3.append(f"passage: {l3}" if l3 else "passage: image")

    if missing > 0:
        print(f"  [경고] 캡션 없는 이미지: {missing}건", flush=True)

    # L1 / L2 / L3 각각 인코딩
    vecs_l1 = _encode(model, texts_l1, "Img L1")
    vecs_l2 = _encode(model, texts_l2, "Img L2")
    vecs_l3 = _encode(model, texts_l3, "Img L3")

    # 저장
    for name, vecs in [("L1", vecs_l1), ("L2", vecs_l2), ("L3", vecs_l3)]:
        out_path = IMG_CACHE / f"cache_img_Im_{name}.npy"
        _backup(out_path)
        np.save(out_path, vecs)
        print(f"  저장: {out_path.name} shape={vecs.shape}", flush=True)

    print(f"  Image Im 재빌드 완료 ({(time.time()-t0)/60:.1f}분)", flush=True)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-only", action="store_true")
    parser.add_argument("--img-only", action="store_true")
    args = parser.parse_args()

    do_doc = not args.img_only
    do_img = not args.doc_only

    print(f"[Step D] Im 캐시 재빌드 시작 (doc={do_doc}, img={do_img})", flush=True)
    t0 = time.time()

    model = _load_bgem3()

    if do_doc:
        rebuild_doc(model)

    if do_img:
        rebuild_img(model)

    print(f"\n[Step D] 전체 완료 ({(time.time()-t0)/60:.1f}분)", flush=True)
    print("  다음 단계: 서버 재시작 후 250케이스 평가 실행")
    print("  cd App/backend && python scripts/evaluate_yplus_250.py")


if __name__ == "__main__":
    main()
