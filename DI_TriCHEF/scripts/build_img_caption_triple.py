"""build_img_caption_triple.py — Img 도메인 BLIP v2 스타일 3단계 캡션 생성.

양자화로 확보된 VRAM 여유를 활용하여 L1(짧은 캡션) + L2(키워드) + L3(상세) 3단계
한국어 캡션을 Qwen2-VL-2B NF4 로 생성하고, BGE-M3 multilingual 임베딩을
각 레벨별로 독립 저장한다.

효과:
  - 쿼리가 유사어, 유의어, 동의어, 비유적 표현으로 들어와도 L1/L2/L3 중 하나와
    매칭될 가능성 증가 → recall 향상
  - L2(키워드)는 BM25 sparse 확장에도 활용 가능
  - 한국어 네이티브 생성 + BGE-M3 cross-lingual → 영어 쿼리도 자연스럽게 처리

출력:
  Data/embedded_DB/Img/captions_triple.jsonl  (per-image L1/L2/L3 텍스트)
  Data/embedded_DB/Img/cache_img_Im_L1.npy    (N, 1024)
  Data/embedded_DB/Img/cache_img_Im_L2.npy    (N, 1024)
  Data/embedded_DB/Img/cache_img_Im_L3.npy    (N, 1024)

실행:
  python DI_TriCHEF/scripts/build_img_caption_triple.py
  python DI_TriCHEF/scripts/build_img_caption_triple.py --resume    # 중단 후 재개
  python DI_TriCHEF/scripts/build_img_caption_triple.py --embed-only  # 캡션 JSONL만 있으면 임베딩만

→ 후속 fuse_img_caption_triple.py 실행 필요:
  python DI_TriCHEF/scripts/fuse_img_caption_triple.py
  (L1/L2/L3 .npy 를 α=0.15/0.25/0.60 으로 가중치 합산 → cache_img_Im.npy 생성)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "DI_TriCHEF"))
sys.path.insert(0, str(_root / "App" / "backend"))

IMG_RAW_DIR    = _root / "Data" / "raw_DB" / "Img"
IMG_CACHE_DIR  = _root / "Data" / "embedded_DB" / "Img"
REG_PATH       = IMG_CACHE_DIR / "registry.json"
OUT_JSONL      = IMG_CACHE_DIR / "captions_triple.jsonl"
PROG_PATH      = IMG_CACHE_DIR / "_caption_triple_progress.json"


def _load_progress() -> dict:
    if PROG_PATH.exists():
        try:
            return json.loads(PROG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_progress(done: dict) -> None:
    PROG_PATH.write_text(
        json.dumps(done, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def stage_caption(resume: bool = True) -> None:
    """1단계: 각 이미지 3단계 캡션 생성 → JSONL append."""
    import numpy as np
    from PIL import Image

    from captioner.qwen_vl_ko import QwenKoCaptioner

    reg = json.loads(REG_PATH.read_text(encoding="utf-8"))
    rels = list(reg.keys())
    total = len(rels)
    print(f"[img_triple] Img 레지스트리 {total}개")

    done = _load_progress() if resume else {}
    if done:
        print(f"  · resume: {len(done)}개 완료 상태 → 건너뜀")

    cap = QwenKoCaptioner(quantize="nf4")

    # JSONL append 모드. 기존 파일이 있고 resume 이면 이어쓰기.
    mode = "a" if (resume and OUT_JSONL.exists()) else "w"
    out_f = OUT_JSONL.open(mode, encoding="utf-8")

    t0 = time.time()
    processed = 0
    errors = 0
    for idx, rel in enumerate(rels, 1):
        if rel in done:
            continue

        img_info = reg[rel]
        abs_path = Path(img_info.get("abs", IMG_RAW_DIR / rel))
        if not abs_path.exists():
            abs_path = IMG_RAW_DIR / rel
        if not abs_path.exists():
            print(f"  [{idx}/{total}] MISSING: {rel}")
            errors += 1
            continue

        try:
            img = Image.open(abs_path).convert("RGB")
            trip = cap.caption_triple(img)
        except Exception as e:
            print(f"  [{idx}/{total}] ERROR {rel}: {e}")
            errors += 1
            continue

        rec = {"rel": rel, "L1": trip["L1"], "L2": trip["L2"], "L3": trip["L3"]}
        out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out_f.flush()

        done[rel] = True
        processed += 1

        if idx % 20 == 0 or idx == total:
            el = time.time() - t0
            rate = processed / max(el, 1e-3)
            eta = (total - idx) / max(rate, 1e-3)
            print(f"  [{idx}/{total}] rel={rel[:50]}  "
                  f"L1={trip['L1'][:30]}  "
                  f"elapsed={el:.0f}s  rate={rate:.2f}/s  eta={eta/60:.1f}min")
            _save_progress(done)

    out_f.close()
    _save_progress(done)
    print(f"[img_triple] 1단계 완료 — 처리 {processed}, 오류 {errors}, "
          f"총 소요 {(time.time()-t0)/60:.1f}분")


def stage_embed() -> None:
    """2단계: captions_triple.jsonl → L1/L2/L3 각각 BGE-M3 임베딩."""
    import numpy as np
    from FlagEmbedding import BGEM3FlagModel

    if not OUT_JSONL.exists():
        print(f"[img_triple] {OUT_JSONL} 없음 — 1단계 먼저 실행하세요.")
        return

    # 레지스트리 순서 유지를 위해 rel → level → text 맵 구축
    reg = json.loads(REG_PATH.read_text(encoding="utf-8"))
    order = list(reg.keys())
    cap_map: dict[str, dict[str, str]] = {}
    with OUT_JSONL.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            cap_map[rec["rel"]] = {"L1": rec.get("L1", " "),
                                   "L2": rec.get("L2", " "),
                                   "L3": rec.get("L3", " ")}

    missing = [r for r in order if r not in cap_map]
    if missing:
        print(f"[img_triple] WARNING: {len(missing)}개 이미지 캡션 없음 — 빈 문자열로 대체")

    L1 = [cap_map.get(r, {}).get("L1", " ") or " " for r in order]
    L2 = [cap_map.get(r, {}).get("L2", " ") or " " for r in order]
    L3 = [cap_map.get(r, {}).get("L3", " ") or " " for r in order]

    print(f"[img_triple] 2단계: BGE-M3 임베딩 — N={len(order)}")
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)

    def embed(texts: list[str]) -> "np.ndarray":
        return model.encode(texts, batch_size=32, max_length=512)["dense_vecs"]

    for level_name, texts, out_name in [
        ("L1", L1, "cache_img_Im_L1.npy"),
        ("L2", L2, "cache_img_Im_L2.npy"),
        ("L3", L3, "cache_img_Im_L3.npy"),
    ]:
        t0 = time.time()
        vecs = embed(texts).astype(np.float32)
        out_path = IMG_CACHE_DIR / out_name
        np.save(out_path, vecs)
        print(f"  · {level_name}: shape={vecs.shape} → {out_path.name}  "
              f"({time.time()-t0:.1f}s)")

    print("[img_triple] 2단계 완료 — unified_engine.py 에서 Im fusion 확장 필요")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--caption-only", action="store_true")
    ap.add_argument("--embed-only", action="store_true")
    ap.add_argument("--no-resume", action="store_true")
    args = ap.parse_args()

    if args.embed_only:
        stage_embed()
        return

    stage_caption(resume=not args.no_resume)

    if not args.caption_only:
        stage_embed()


if __name__ == "__main__":
    main()
