"""scripts/repair_doc_im_combined_v3.py — Doc Im 축 결합 재구축 v3

목적: v2 완료 후 page_text만 사용했던 ~31,857 페이지에 대해
     시각 콘텐츠(그래프·사진·표·다이어그램)가 있는 페이지를 선별,
     Qwen VL 캡셔닝 후 page_text + Qwen 캡션을 결합하여 Im 축 재임베딩.

처리 흐름:
  Phase 0 (CPU 16스레드): PNG 썸네일 분석으로 시각 콘텐츠 페이지 선별 (~2분)
  Phase 1 (GPU batch=8 + CPU): 선별 페이지 Qwen VL 캡셔닝 (GPU+CPU 병렬)
  Phase 2 (CPU):  page_text + Qwen 캡션 결합
  Phase 3 (GPU):  변경 페이지만 BGE-M3 증분 Im 재임베딩
  Phase 4 (CPU+GPU): 직교화 → Im 캐시 업데이트 → ChromaDB 증분 upsert
  Phase 5 (CPU):  lexical/sparse 재빌드

최적화:
  - batch_size=8, MAX_IMG_SIDE=768 → VRAM ~4.7GB (8GB RTX 4070 안전)
  - CPU ThreadPool: 이미지 프리페치 + 캡션 저장 GPU와 동시 진행
  - 변경 페이지만 BGE-M3 재임베딩 (전체 재처리 불필요)
  - 변경 페이지만 ChromaDB upsert

실행: python scripts/repair_doc_im_combined_v3.py
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PATHS, TRICHEF_CFG

# ── 로깅 ──────────────────────────────────────────────────────────────────────
LOG_FILE = Path(PATHS["DATA_ROOT"]).parent / "logs" / "repair_im_v3.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── 경로 ──────────────────────────────────────────────────────────────────────
EXTRACT  = Path(PATHS["TRICHEF_DOC_EXTRACT"])
CACHE    = Path(PATHS["TRICHEF_DOC_CACHE"])
PT_BASE  = EXTRACT / "page_text"
CAP_BASE = EXTRACT / "captions"
PI_BASE  = EXTRACT / "page_images"
IDS_FILE = CACHE / "doc_page_ids.json"

# ── 설정 ──────────────────────────────────────────────────────────────────────
BATCH_SIZE    = 8     # Qwen 배치 크기 (NF4 1.2GB + 8이미지 ≈ 3.5GB → 총 ~4.7GB)
MAX_IMG_SIDE  = 768   # 이미지 최대 해상도 (896→768 VRAM 절감)
CPU_WORKERS   = min(16, os.cpu_count() or 4)

# 시각 콘텐츠 감지 임계값
SAT_THRESHOLD   = 0.04   # 채도 비율: 이 이상이면 컬러 그래프/사진 포함
TEXT_LEN_THRESH = 350    # page_text 이 이하면 다이어그램·표 포함 가능성 높음

# 결합 구분자
COMBINE_SEP = "\n\n[시각 분석]\n"


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _is_english_only(text: str) -> bool:
    return bool(text) and not any("가" <= c <= "힣" for c in text)


def _page_stem(entry: str) -> tuple[str, str]:
    """entry → (folder, page_stem)"""
    parts = entry.split("/")
    return parts[1], Path(parts[2]).stem


def _read_page_text(entry: str) -> str:
    folder, stem = _page_stem(entry)
    pt = PT_BASE / folder / f"{stem}.txt"
    try:
        return pt.read_text(encoding="utf-8").strip() if pt.exists() else ""
    except Exception:
        return ""


def _read_caption(entry: str) -> str:
    folder, stem = _page_stem(entry)
    cap = CAP_BASE / folder / f"{stem}.txt"
    try:
        return cap.read_text(encoding="utf-8", errors="replace").strip() if cap.exists() else ""
    except Exception:
        return ""


def _text_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


# ── Phase 0: 시각 콘텐츠 감지 ─────────────────────────────────────────────────

def _detect_visual(entry: str) -> tuple[str, bool]:
    """
    (entry, has_visual_content) 반환.
    PNG 썸네일 채도 분석 + page_text 길이로 시각 콘텐츠 여부 판별.
    """
    from PIL import Image

    folder, stem = _page_stem(entry)

    # 1) page_text 길이 확인 (짧으면 이미지/표 중심)
    pt_text = _read_page_text(entry)
    if len(pt_text) < TEXT_LEN_THRESH:
        return entry, True

    # 2) PNG 채도 분석 (컬러 그래프·사진 감지)
    parts = entry.split("/")
    img_path = PI_BASE / folder / parts[2]
    if not img_path.exists():
        return entry, False
    try:
        img = Image.open(img_path).convert("RGB")
        img.thumbnail((128, 128), Image.LANCZOS)
        arr = np.array(img, dtype=np.float32)
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        max_c = np.maximum(np.maximum(r, g), b)
        min_c = np.minimum(np.minimum(r, g), b)
        saturation = (max_c - min_c) / (max_c + 1e-6)
        sat_ratio = float(np.mean(saturation > 0.25))
        return entry, sat_ratio > SAT_THRESHOLD
    except Exception:
        return entry, False


def phase0_detect(ids: list[str]) -> list[str]:
    """page_text 보유 페이지 중 시각 콘텐츠 포함 페이지 선별."""
    # v2 완료 후: Qwen 캡션이 이미 있는 페이지는 제외 (이미 처리됨)
    # → CAP_BASE에 캡션 파일이 없고 page_text가 있는 페이지만 대상
    candidates = []
    for e in ids:
        folder, stem = _page_stem(e)
        pt = PT_BASE / folder / f"{stem}.txt"
        cap = CAP_BASE / folder / f"{stem}.txt"
        # page_text 있고 캡션 없으면 후보
        if pt.exists() and not cap.exists():
            candidates.append(e)

    log.info(f"[Phase0] 후보 {len(candidates):,}페이지 시각 콘텐츠 감지 중 (CPU {CPU_WORKERS}스레드)...")
    t0 = time.time()

    visual_pages = []
    with ThreadPoolExecutor(max_workers=CPU_WORKERS) as ex:
        for entry, has_visual in ex.map(_detect_visual, candidates):
            if has_visual:
                visual_pages.append(entry)

    log.info(
        f"[Phase0] 완료 ({time.time()-t0:.0f}s) — "
        f"후보 {len(candidates):,} → 시각 콘텐츠 {len(visual_pages):,}페이지 선별"
    )
    return visual_pages


# ── Phase 1: 선별 페이지 Qwen VL 캡셔닝 ──────────────────────────────────────

def _load_image(entry: str):
    """CPU: 이미지 로드 + 리사이즈. (entry, folder, stem, pil_img|None)"""
    from PIL import Image
    parts = entry.split("/")
    folder, page_file = parts[1], parts[2]
    stem = Path(page_file).stem
    img_path = PI_BASE / folder / page_file
    try:
        im = Image.open(img_path).convert("RGB")
        w, h = im.size
        if max(w, h) > MAX_IMG_SIDE:
            ratio = MAX_IMG_SIDE / max(w, h)
            im = im.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        return entry, folder, stem, im
    except Exception as e:
        log.warning(f"  이미지 로드 실패 {page_file}: {e}")
        return entry, folder, stem, None


def _save_captions_batch(jobs: list[tuple[str, str, str]]) -> None:
    """CPU: 캡션 파일 저장. (folder, stem, text)"""
    for folder, stem, text in jobs:
        if not text:
            continue
        try:
            p = CAP_BASE / folder / f"{stem}.txt"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        except Exception:
            pass


def phase1_qwen(visual_pages: list[str], captions: dict[str, str]) -> None:
    """GPU batch=8 + CPU 병렬로 시각 페이지 Qwen VL 캡셔닝."""
    if not visual_pages:
        log.info("[Phase1] 시각 콘텐츠 페이지 없음 — 스킵")
        return

    log.info(f"[Phase1] Qwen VL 캡셔닝 시작 (batch={BATCH_SIZE}, {len(visual_pages):,}페이지)...")

    from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
    from qwen_vl_utils import process_vision_info  # type: ignore

    log.info("  Qwen2-VL-2B NF4 로드 중...")
    t0 = time.time()
    model = Qwen2VLForConditionalGeneration.from_pretrained(
        "Qwen/Qwen2-VL-2B-Instruct",
        dtype=torch.float16,
        device_map="cuda",
        quantization_config=_get_bnb_config(),
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

    def _build_msgs(pil_img):
        return [{"role": "user", "content": [
            {"type": "image", "image": pil_img},
            {"type": "text",  "text": PROMPT},
        ]}]

    def _infer_batch(imgs: list, metas: list) -> list[str]:
        texts_batch = [
            processor.apply_chat_template(_build_msgs(im), tokenize=False, add_generation_prompt=True)
            for im in imgs
        ]
        image_inputs, video_inputs = process_vision_info([_build_msgs(im) for im in imgs])
        inputs = processor(
            text=texts_batch, images=image_inputs, videos=video_inputs,
            padding=True, return_tensors="pt",
        ).to("cuda")
        with torch.no_grad():
            out_ids = model.generate(**inputs, max_new_tokens=200, do_sample=False)
        trimmed = [out_ids[i][len(inputs.input_ids[i]):] for i in range(len(imgs))]
        return processor.batch_decode(trimmed, skip_special_tokens=True)

    total = len(visual_pages)
    done = 0
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=4) as cpu_loader, \
         ThreadPoolExecutor(max_workers=4) as cpu_saver:

        for batch_start in range(0, total, BATCH_SIZE):
            batch_raw = visual_pages[batch_start:batch_start + BATCH_SIZE]
            loaded = list(cpu_loader.map(_load_image, batch_raw))

            valid_imgs = [r[3] for r in loaded if r[3] is not None]
            valid_meta = [(r[0], r[1], r[2]) for r in loaded if r[3] is not None]
            invalid_meta = [(r[0], r[1], r[2]) for r in loaded if r[3] is None]

            caps = []
            if valid_imgs:
                try:
                    caps = _infer_batch(valid_imgs, valid_meta)
                except Exception as e:
                    log.warning(f"  배치 추론 실패 (batch_start={batch_start}): {e}")
                    caps = [""] * len(valid_imgs)

            save_jobs = []
            for (entry, folder, stem), cap in zip(valid_meta, caps):
                captions[entry] = cap
                save_jobs.append((folder, stem, cap))
            for entry, folder, stem in invalid_meta:
                captions[entry] = ""

            cpu_saver.submit(_save_captions_batch, save_jobs)

            done += len(batch_raw)
            if done % 100 == 0 or done == total:
                elapsed = time.time() - t_start
                rate = done / elapsed if elapsed > 0 else 0
                rem = (total - done) / rate if rate > 0 else 0
                log.info(f"  Qwen {done:,}/{total:,} | {rate:.2f}p/s | 잔여 {rem/60:.0f}분")

    del model
    torch.cuda.empty_cache()
    import gc; gc.collect()
    log.info("[Phase1] 완료 — VRAM 해제")


def _get_bnb_config():
    """BitsAndBytesConfig NF4 (deprecated 경고 없는 신식 API)."""
    try:
        from transformers import BitsAndBytesConfig
        return BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
        )
    except Exception:
        return None


# ── Phase 2: 소스 결합 ────────────────────────────────────────────────────────

def phase2_combine(ids: list[str], captions: dict[str, str]) -> dict[str, str]:
    """
    page_text + Qwen 캡션 결합.
    반환: {entry: combined_text} (변경된 페이지만)
    """
    log.info("[Phase2] page_text + Qwen 캡션 결합 중...")
    changed: dict[str, str] = {}
    for entry in ids:
        pt = _read_page_text(entry)
        cap = captions.get(entry) or _read_caption(entry)

        if pt and cap and not _is_english_only(cap):
            combined = pt + COMBINE_SEP + cap
        elif pt:
            combined = pt
        elif cap and not _is_english_only(cap):
            combined = cap
        else:
            combined = pt or cap or ""

        # 현재 캡션 파일 내용과 비교해 변경 여부 판단
        folder, stem = _page_stem(entry)
        cap_file = CAP_BASE / folder / f"{stem}.txt"
        existing = ""
        if cap_file.exists():
            try:
                existing = cap_file.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                pass

        # combined이 기존 Im 소스(page_text 또는 캡션)보다 풍부하면 변경으로 간주
        if combined != existing and combined:
            changed[entry] = combined

    log.info(f"[Phase2] 완료 — 변경 페이지: {len(changed):,}")
    return changed


# ── Phase 3: BGE-M3 증분 Im 재임베딩 ─────────────────────────────────────────

def phase3_embed_incremental(changed: dict[str, str], all_ids: list[str]) -> tuple[np.ndarray, list[int]]:
    """
    변경 페이지만 BGE-M3 Im 재임베딩.
    반환: (Im_full 업데이트된 배열, 변경된 인덱스 목록)
    """
    if not changed:
        log.info("[Phase3] 변경 페이지 없음 — 스킵")
        Im = np.load(CACHE / "cache_doc_page_Im.npy").astype(np.float32)
        return Im, []

    log.info(f"[Phase3] BGE-M3 증분 Im 재임베딩: {len(changed):,}페이지...")
    from embedders.trichef import bgem3_caption_im as im_emb

    # 변경 페이지 인덱스 + 텍스트
    idx_map = {e: i for i, e in enumerate(all_ids)}
    changed_indices = [idx_map[e] for e in changed if e in idx_map]
    changed_entries = [e for e in changed if e in idx_map]
    changed_texts = [changed[e] for e in changed_entries]

    new_vecs = im_emb.embed_passage(changed_texts)  # (N_changed, 1024)
    log.info(f"[Phase3] 새 임베딩 shape={new_vecs.shape}")

    # 기존 Im 캐시 로드 후 변경 행 업데이트
    Im = np.load(CACHE / "cache_doc_page_Im.npy").astype(np.float32)
    for arr_idx, new_vec in zip(changed_indices, new_vecs):
        Im[arr_idx] = new_vec.astype(np.float32)

    log.info("[Phase3] 완료")
    return Im, changed_indices


# ── Phase 4: 직교화 + 증분 ChromaDB upsert ───────────────────────────────────

def phase4_update(
    all_ids: list[str],
    Im_full: np.ndarray,
    changed_indices: list[int],
) -> None:
    if not changed_indices:
        log.info("[Phase4] 변경 없음 — 스킵")
        return

    log.info(f"[Phase4] 직교화 + ChromaDB 증분 upsert ({len(changed_indices):,}페이지)...")
    Re = np.load(CACHE / "cache_doc_page_Re.npy").astype(np.float32)
    Z  = np.load(CACHE / "cache_doc_page_Z.npy").astype(np.float32)

    from services.trichef import tri_gs
    from embedders.trichef.incremental_runner import _upsert_chroma

    Im_perp, Z_perp = tri_gs.orthogonalize(Re, Im_full, Z)

    # Im 캐시 저장
    np.save(CACHE / "cache_doc_page_Im.npy", Im_full)
    log.info("  Im 캐시 저장 완료")

    # 변경 페이지만 ChromaDB upsert
    sub_ids    = [all_ids[i]    for i in changed_indices]
    sub_Re     = Re[changed_indices]
    sub_Im     = Im_perp[changed_indices]
    sub_Z      = Z_perp[changed_indices]

    _upsert_chroma(TRICHEF_CFG["COL_DOC_PAGE"], sub_ids, sub_Re, sub_Im, sub_Z, EXTRACT)

    try:
        from services.chroma_async import drain_and_wait
        drain_and_wait()
    except Exception:
        pass

    log.info("[Phase4] 완료")


# ── Phase 5: lexical 재빌드 ───────────────────────────────────────────────────

def phase5_sparse() -> None:
    log.info("[Phase5] sparse/lexical 재빌드...")
    from services.trichef import lexical_rebuild
    lexical_rebuild.rebuild_doc_lexical()
    log.info("[Phase5] 완료")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=== Doc Im 축 결합 재구축 v3 (GPU batch=8 + CPU 16스레드) ===")
    t_total = time.time()

    with open(IDS_FILE, encoding="utf-8") as f:
        all_ids: list[str] = json.load(f)["ids"]
    log.info(f"총 페이지: {len(all_ids):,}")

    # Phase 0: 시각 콘텐츠 페이지 선별
    visual_pages = phase0_detect(all_ids)

    # Phase 1: 선별 페이지 Qwen VL 캡셔닝
    new_captions: dict[str, str] = {}
    phase1_qwen(visual_pages, new_captions)

    # Phase 2: page_text + Qwen 결합 (변경 페이지만 추출)
    changed = phase2_combine(all_ids, new_captions)

    # Phase 3: 변경 페이지만 BGE-M3 증분 재임베딩
    Im_full, changed_indices = phase3_embed_incremental(changed, all_ids)

    # Phase 4: 직교화 + Im 캐시 + ChromaDB 증분 upsert
    phase4_update(all_ids, Im_full, changed_indices)

    # Phase 5: lexical 재빌드
    phase5_sparse()

    elapsed = (time.time() - t_total) / 60
    log.info(f"=== 전체 완료 ({elapsed:.0f}분 소요) ===")
    log.info(f"  처리 요약: 시각 감지 {len(visual_pages):,} → Im 업데이트 {len(changed_indices):,}페이지")


if __name__ == "__main__":
    main()
