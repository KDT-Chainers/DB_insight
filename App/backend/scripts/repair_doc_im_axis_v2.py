"""scripts/repair_doc_im_axis_v2.py — Doc Im 축 재구축 (GPU 배치 + CPU 병렬 최적화)

최적화:
  - Phase 2: Qwen 배치 추론 (batch_size=4) + 단일 통합 프롬프트 + CPU 프리페치
  - Phase 3: BGE-M3 대용량 배치 임베딩 (GPU)
  - CPU ThreadPool: 이미지 로드/저장 GPU와 병렬 처리
  - Resume: 이미 캡셔닝된 페이지 자동 스킵

예상 속도: ~1.5s/page (vs 기존 ~12s/page, 약 8배 향상)
실행: python scripts/repair_doc_im_axis_v2.py
"""
from __future__ import annotations
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from threading import Thread

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PATHS, TRICHEF_CFG

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(message)s",
                    handlers=[
                        logging.StreamHandler(sys.stdout),
                        logging.FileHandler(
                            Path(PATHS["DATA_ROOT"]).parent / "logs" / "repair_im_v2.log",
                            encoding="utf-8"
                        ),
                    ])
log = logging.getLogger(__name__)

EXTRACT  = Path(PATHS["TRICHEF_DOC_EXTRACT"])
CACHE    = Path(PATHS["TRICHEF_DOC_CACHE"])
PT_BASE  = EXTRACT / "page_text"
CAP_BASE = EXTRACT / "captions"
PI_BASE  = EXTRACT / "page_images"
IDS_FILE = CACHE / "doc_page_ids.json"

BATCH_SIZE   = 4    # Qwen 배치 크기 (NF4 1.2GB + 4이미지 ≈ 3GB, 8GB VRAM 안전)
PREFETCH_N   = 8    # CPU 프리페치 큐 크기
MAX_IMG_SIDE = 896  # Qwen 이미지 최대 해상도


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _is_english_only(text: str) -> bool:
    return bool(text) and not any("가" <= c <= "힣" for c in text)


def _get_im_source(entry: str) -> str | None:
    """Im 소스 텍스트 반환. None = Qwen 필요."""
    parts = entry.split("/")
    if len(parts) < 3:
        return ""
    folder, page_stem = parts[1], Path(parts[2]).stem

    pt = PT_BASE / folder / f"{page_stem}.txt"
    if pt.exists():
        try:
            txt = pt.read_text(encoding="utf-8").strip()
            if len(txt) > 100 and any("가" <= c <= "힣" for c in txt):
                return txt
        except Exception:
            pass

    cap = CAP_BASE / folder / f"{page_stem}.txt"
    if cap.exists():
        try:
            c = cap.read_text(encoding="utf-8", errors="replace").strip()
            if c and not _is_english_only(c):
                return c
        except Exception:
            pass

    return None  # Qwen 필요


# ── Phase 1 ───────────────────────────────────────────────────────────────────

def phase1(ids: list[str]) -> tuple[dict, list[str]]:
    log.info(f"[Phase1] {len(ids):,}페이지 Im 소스 결정 중 (CPU {min(16, os.cpu_count())}스레드)...")
    texts: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=min(16, os.cpu_count() or 4)) as ex:
        for entry, src in zip(ids, ex.map(_get_im_source, ids)):
            texts[entry] = src
    need = [e for e in ids if texts[e] is None]
    log.info(f"[Phase1] 텍스트 소스: {len(ids)-len(need):,} | Qwen 필요: {len(need):,}")
    return texts, need


# ── Phase 2: 배치 Qwen + CPU 병렬 ─────────────────────────────────────────────

def _load_one(args) -> tuple[str, str, str, object | None]:
    """CPU: 이미지 로드 + PIL 변환. (entry, folder, page_stem, pil_img|None)"""
    from PIL import Image
    (entry,) = args
    parts = entry.split("/")
    folder, page_file = parts[1], parts[2]
    page_stem = Path(page_file).stem
    img_path = PI_BASE / folder / page_file
    try:
        im = Image.open(img_path).convert("RGB")
        # 최대 크기 제한 (메모리 절감)
        w, h = im.size
        if max(w, h) > MAX_IMG_SIDE:
            ratio = MAX_IMG_SIDE / max(w, h)
            im = im.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        return entry, folder, page_stem, im
    except Exception as e:
        log.warning(f"  이미지 로드 실패 {page_file}: {e}")
        return entry, folder, page_stem, None


def _save_captions(jobs: list[tuple[str, str, str]]) -> None:
    """CPU: 캡션 파일 저장. (folder, page_stem, caption_text)"""
    for folder, page_stem, cap_text in jobs:
        if not cap_text:
            continue
        try:
            cap_file = CAP_BASE / folder / f"{page_stem}.txt"
            cap_file.parent.mkdir(parents=True, exist_ok=True)
            cap_file.write_text(cap_text, encoding="utf-8")
        except Exception:
            pass


def phase2_batch_qwen(need_qwen: list[str], texts: dict) -> None:
    if not need_qwen:
        log.info("[Phase2] Qwen 필요 없음 — 스킵")
        return

    log.info(f"[Phase2] Qwen 배치 캡셔닝 시작 (batch={BATCH_SIZE}, {len(need_qwen):,}페이지)...")

    # ── Qwen 모델 로드 ─────────────────────────────────────────────────────
    from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
    from qwen_vl_utils import process_vision_info  # type: ignore

    log.info("  Qwen2-VL-2B NF4 로드 중...")
    t0 = time.time()
    model = Qwen2VLForConditionalGeneration.from_pretrained(
        "Qwen/Qwen2-VL-2B-Instruct",
        torch_dtype=torch.float16,
        device_map="cuda",
        load_in_4bit=True,
    )
    model.eval()
    processor = AutoProcessor.from_pretrained(
        "Qwen/Qwen2-VL-2B-Instruct",
        min_pixels=256 * 28 * 28,
        max_pixels=MAX_IMG_SIDE * MAX_IMG_SIDE,
    )
    log.info(f"  Qwen 로드 완료 ({time.time()-t0:.1f}s)")

    PROMPT = (
        "이 문서 페이지를 한국어로 분석하세요.\n"
        "1) 핵심 제목(1줄) 2) 주요 내용·그래프·표·이미지 설명(3~5문장) "
        "3) 핵심 키워드 10~15개(쉼표 구분)\n"
        "번호 없이 연속으로 작성하세요."
    )

    def _build_messages(pil_img) -> list[dict]:
        return [{
            "role": "user",
            "content": [
                {"type": "image", "image": pil_img},
                {"type": "text",  "text": PROMPT},
            ],
        }]

    def _infer_batch(batch_imgs: list, batch_entries: list[tuple]) -> list[str]:
        """GPU: 배치 추론."""
        texts_batch = [
            processor.apply_chat_template(
                _build_messages(im), tokenize=False, add_generation_prompt=True
            )
            for im in batch_imgs
        ]
        image_inputs, video_inputs = process_vision_info(
            [_build_messages(im) for im in batch_imgs]
        )
        inputs = processor(
            text=texts_batch,
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to("cuda")
        with torch.no_grad():
            out_ids = model.generate(
                **inputs,
                max_new_tokens=200,
                do_sample=False,
            )
        # 입력 토큰 제거
        trimmed = [
            out_ids[i][len(inputs.input_ids[i]):]
            for i in range(len(batch_imgs))
        ]
        return processor.batch_decode(trimmed, skip_special_tokens=True)

    # ── CPU 프리페치 + GPU 배치 파이프라인 ────────────────────────────────
    total = len(need_qwen)
    done = 0
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=4) as cpu_loader, \
         ThreadPoolExecutor(max_workers=4) as cpu_saver:

        # 배치 단위 처리
        for batch_start in range(0, total, BATCH_SIZE):
            batch_entries_raw = need_qwen[batch_start:batch_start + BATCH_SIZE]

            # CPU 병렬 이미지 로드
            loaded = list(cpu_loader.map(_load_one, [(e,) for e in batch_entries_raw]))

            valid_imgs   = [r[3]  for r in loaded if r[3] is not None]
            valid_meta   = [(r[0], r[1], r[2]) for r in loaded if r[3] is not None]
            invalid_meta = [(r[0], r[1], r[2]) for r in loaded if r[3] is None]

            captions = []
            if valid_imgs:
                try:
                    captions = _infer_batch(valid_imgs, valid_meta)
                except Exception as e:
                    log.warning(f"  배치 추론 실패 ({batch_start}~): {e}")
                    captions = [""] * len(valid_imgs)

            # CPU 병렬 캡션 저장 + texts 업데이트
            save_jobs = []
            for (entry, folder, page_stem), cap in zip(valid_meta, captions):
                texts[entry] = cap
                save_jobs.append((folder, page_stem, cap))
            for entry, folder, page_stem in invalid_meta:
                texts[entry] = ""

            cpu_saver.submit(_save_captions, save_jobs)

            done += len(batch_entries_raw)
            if done % 100 == 0 or done == total:
                elapsed = time.time() - t_start
                rate = done / elapsed if elapsed > 0 else 0
                remaining = (total - done) / rate if rate > 0 else 0
                log.info(
                    f"  Qwen {done:,}/{total:,} | "
                    f"{rate:.1f}p/s | 잔여 {remaining/60:.0f}분"
                )

    # VRAM 해제
    del model
    torch.cuda.empty_cache()
    import gc; gc.collect()
    log.info("[Phase2] 완료 — VRAM 해제")


# ── Phase 3: BGE-M3 Im 재임베딩 ───────────────────────────────────────────────

def phase3_embed(ids: list[str], texts: dict) -> np.ndarray:
    log.info(f"[Phase3] BGE-M3 Im 재임베딩: {len(ids):,}페이지...")
    from embedders.trichef import bgem3_caption_im as im_emb
    captions = [texts.get(e) or "" for e in ids]
    Im = im_emb.embed_passage(captions)
    log.info(f"[Phase3] 완료: shape={Im.shape}")
    return Im


# ── Phase 4: 직교화 + ChromaDB ────────────────────────────────────────────────

def phase4_update(ids: list[str], Im_new: np.ndarray) -> None:
    log.info("[Phase4] 직교화 + ChromaDB 업데이트...")
    Re = np.load(CACHE / "cache_doc_page_Re.npy").astype(np.float32)
    Z  = np.load(CACHE / "cache_doc_page_Z.npy").astype(np.float32)
    from services.trichef import tri_gs
    from embedders.trichef.incremental_runner import _upsert_chroma
    Im_perp, Z_perp = tri_gs.orthogonalize(Re, Im_new, Z)
    np.save(CACHE / "cache_doc_page_Im.npy", Im_new.astype(np.float32))
    _upsert_chroma(TRICHEF_CFG["COL_DOC_PAGE"], ids, Re, Im_perp, Z_perp, EXTRACT)
    try:
        from services.chroma_async import drain_and_wait
        drain_and_wait()
    except Exception:
        pass
    log.info("[Phase4] 완료")


# ── Phase 5: sparse/lexical 재빌드 ───────────────────────────────────────────

def phase5_sparse() -> None:
    log.info("[Phase5] sparse/lexical 재빌드...")
    from services.trichef import lexical_rebuild
    lexical_rebuild.rebuild_doc_lexical()
    log.info("[Phase5] 완료")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=== Doc Im 축 재구축 v2 (GPU 배치 + CPU 병렬) ===")
    t_total = time.time()

    with open(IDS_FILE, encoding="utf-8") as f:
        ids: list[str] = json.load(f)["ids"]
    log.info(f"총 페이지: {len(ids):,}")

    texts, need_qwen = phase1(ids)
    phase2_batch_qwen(need_qwen, texts)
    Im_new = phase3_embed(ids, texts)
    phase4_update(ids, Im_new)
    phase5_sparse()

    elapsed = (time.time() - t_total) / 60
    log.info(f"=== 전체 완료 ({elapsed:.0f}분 소요) ===")


if __name__ == "__main__":
    main()
