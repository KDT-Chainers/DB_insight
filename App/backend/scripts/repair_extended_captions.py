"""scripts/repair_extended_captions.py — 확장 불량캡션 탐지 + Qwen 재캡셔닝 + 증분 Im 재임베딩

기존 repair_caption_quality.py 대비 추가 탐지 패턴:
  - 줄 내 n-gram 반복 ("the korean version of the korean version of the...")
  - 영어 전용 캡션 + 충분한 한국어 page_text 불일치

최적화:
  - Qwen batch=8, CPU 8스레드 이미지 프리페치 (GPU+CPU 병렬)
  - BGE-M3 증분 임베딩 (변경 페이지만)
  - ChromaDB 증분 upsert

실행: python scripts/repair_extended_captions.py
"""
from __future__ import annotations
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PATHS, TRICHEF_CFG

LOG_FILE = Path(PATHS["DATA_ROOT"]).parent / "logs" / "repair_extended_captions.log"
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

EXTRACT  = Path(PATHS["TRICHEF_DOC_EXTRACT"])
CACHE    = Path(PATHS["TRICHEF_DOC_CACHE"])
CAP_BASE = EXTRACT / "captions"
PT_BASE  = EXTRACT / "page_text"
PI_BASE  = EXTRACT / "page_images"
IDS_FILE = CACHE / "doc_page_ids.json"

BATCH_SIZE   = 16     # NF4 + batch=16 @ 512px ≈ 6GB, RTX 4070 8GB 안전 (2× 처리량)
CPU_WORKERS  = 8      # CPU 병렬 스레드 (이미지 로드/저장 I/O)
MAX_IMG_SIDE = 512    # 768→512: 시각 토큰 ~55% 감소, 속도 2~3× 향상, 품질 충분

PROMPT = (
    "이 문서 페이지를 한국어로 분석하세요.\n"
    "1) 핵심 제목(1줄) 2) 주요 내용·그래프·표·이미지 설명(3~5문장) "
    "3) 핵심 키워드 10~15개(쉼표 구분)\n"
    "번호 없이 연속으로 작성하세요."
)


# ── 확장 불량 캡션 탐지 ────────────────────────────────────────────────────────

def _is_bad_caption_extended(cap_text: str, page_text: str = "") -> bool:
    """확장 불량 캡션 탐지. 기존 패턴 + n-gram 반복 + 영문 전용 불일치."""
    if not cap_text:
        return False

    # 1) 소수점 반복 (1.1.1.1...)
    if re.search(r'(\b\d+\.\d+\.){3,}', cap_text):
        return True

    # 2) 줄 단위 동일 문장 3회 이상 반복
    lines = [l.strip() for l in re.split(r'[\n。]', cap_text) if l.strip()]
    counts = Counter(lines)
    if any(v >= 3 for v in counts.values()):
        return True

    # 3) 줄 내 n-gram 반복 ("the X of the X of the X...")
    for line in lines:
        words = line.split()
        for n in range(3, 6):
            if len(words) < n * 3:
                continue
            ngrams = [' '.join(words[i:i+n]) for i in range(len(words)-n+1)]
            ng_counts = Counter(ngrams)
            if any(v >= 3 for v in ng_counts.values()):
                return True

    # 4) 영문 전용 캡션 + page_text도 한국어 100자 미만 (Im 소스 모두 불량)
    #    → page_text가 충분한 한국어면 v2에서 이미 page_text로 Im 임베딩 완료
    ko_in_cap = sum(1 for c in cap_text  if '가' <= c <= '힣')
    ko_in_pt  = sum(1 for c in page_text if '가' <= c <= '힣')
    if ko_in_cap == 0 and ko_in_pt < 100:
        return True

    return False


# ── Phase 0: 확장 스캔 ────────────────────────────────────────────────────────

def _scan_one(args: tuple) -> tuple[str, bool]:
    """(entry) → (entry, is_bad)"""
    (entry,) = args
    parts = entry.split("/")
    if len(parts) < 3:
        return entry, False
    folder, page_file = parts[1], parts[2]
    page_stem = Path(page_file).stem

    cap_path = CAP_BASE / folder / f"{page_stem}.txt"
    pt_path  = PT_BASE  / folder / f"{page_stem}.txt"

    cap_text = ""
    if cap_path.exists():
        try:
            cap_text = cap_path.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            pass

    pt_text = ""
    if pt_path.exists():
        try:
            pt_text = pt_path.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            pass

    return entry, _is_bad_caption_extended(cap_text, pt_text)


def phase0_scan(all_ids: list[str]) -> list[str]:
    """전체 entry 스캔 → 불량 entry 목록 반환."""
    log.info(f"[Phase0] 확장 캡션 스캔: {len(all_ids):,}페이지 (CPU {CPU_WORKERS}스레드)...")
    t0 = time.time()
    bad: list[str] = []
    with ThreadPoolExecutor(max_workers=CPU_WORKERS) as ex:
        for entry, is_bad in ex.map(_scan_one, [(e,) for e in all_ids]):
            if is_bad:
                bad.append(entry)
    log.info(
        f"[Phase0] 완료 ({time.time()-t0:.1f}s) "
        f"-- 불량 {len(bad):,} / 전체 {len(all_ids):,}"
    )
    return bad


# ── Phase 1: Qwen 재캡셔닝 (GPU batch + CPU 병렬 프리페치) ──────────────────────

def _load_one(args: tuple):
    """CPU: PIL 이미지 로드 + 리사이즈."""
    from PIL import Image
    (entry,) = args
    parts = entry.split("/")
    folder, page_file = parts[1], parts[2]
    page_stem = Path(page_file).stem
    img_path = PI_BASE / folder / page_file
    try:
        im = Image.open(img_path).convert("RGB")
        w, h = im.size
        if max(w, h) > MAX_IMG_SIDE:
            ratio = MAX_IMG_SIDE / max(w, h)
            im = im.resize((int(w*ratio), int(h*ratio)), Image.LANCZOS)
        return entry, folder, page_stem, im
    except Exception as e:
        log.warning(f"  이미지 로드 실패 {page_file}: {e}")
        return entry, folder, page_stem, None


def _save_captions(jobs: list[tuple]) -> None:
    """CPU: 캡션 파일 저장."""
    for folder, page_stem, cap_text in jobs:
        if not cap_text:
            continue
        try:
            p = CAP_BASE / folder / f"{page_stem}.txt"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(cap_text, encoding="utf-8")
        except Exception:
            pass


def phase1_qwen(bad_entries: list[str]) -> dict[str, str]:
    """불량 캡션 페이지만 Qwen 재캡셔닝. entry→new_caption 반환."""
    if not bad_entries:
        log.info("[Phase1] 재캡셔닝 대상 없음 — 스킵")
        return {}

    log.info(f"[Phase1] Qwen2-VL 재캡셔닝: {len(bad_entries):,}페이지 (batch={BATCH_SIZE})...")
    from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
    from qwen_vl_utils import process_vision_info  # type: ignore

    t0 = time.time()
    model = Qwen2VLForConditionalGeneration.from_pretrained(
        "Qwen/Qwen2-VL-2B-Instruct",
        torch_dtype=torch.float16,
        device_map="cuda",
        load_in_4bit=True,
        attn_implementation="eager",   # flash_attn 미설치 환경 안전 fallback
    )
    model.eval()
    # min_pixels 낮춤: 작은 문서 이미지 과도 패딩 방지 → 토큰 절약
    processor = AutoProcessor.from_pretrained(
        "Qwen/Qwen2-VL-2B-Instruct",
        min_pixels=128 * 28 * 28,
        max_pixels=MAX_IMG_SIDE * MAX_IMG_SIDE,
    )
    log.info(f"  Qwen 로드 완료 ({time.time()-t0:.1f}s)")

    def _build_msgs(pil_img):
        return [{"role": "user", "content": [
            {"type": "image", "image": pil_img},
            {"type": "text",  "text": PROMPT},
        ]}]

    def _infer_batch(imgs: list) -> list[str]:
        texts_in = [
            processor.apply_chat_template(_build_msgs(im), tokenize=False, add_generation_prompt=True)
            for im in imgs
        ]
        img_inputs, vid_inputs = process_vision_info([_build_msgs(im) for im in imgs])
        inputs = processor(
            text=texts_in, images=img_inputs, videos=vid_inputs,
            padding=True, return_tensors="pt",
        ).to("cuda")
        with torch.no_grad():
            out_ids = model.generate(**inputs, max_new_tokens=200, do_sample=False)
        trimmed = [out_ids[i][len(inputs.input_ids[i]):] for i in range(len(imgs))]
        return processor.batch_decode(trimmed, skip_special_tokens=True)

    new_caps: dict[str, str] = {}
    total = len(bad_entries)
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=CPU_WORKERS) as cpu_loader, \
         ThreadPoolExecutor(max_workers=4)           as cpu_saver:

        for batch_start in range(0, total, BATCH_SIZE):
            batch_raw = bad_entries[batch_start:batch_start + BATCH_SIZE]
            loaded = list(cpu_loader.map(_load_one, [(e,) for e in batch_raw]))

            valid   = [(r[0], r[1], r[2], r[3]) for r in loaded if r[3] is not None]
            invalid = [(r[0], r[1], r[2])        for r in loaded if r[3] is None]

            captions: list[str] = []
            if valid:
                try:
                    captions = _infer_batch([v[3] for v in valid])
                except Exception as e:
                    log.warning(f"  배치 추론 실패 ({batch_start}~): {e}")
                    captions = [""] * len(valid)

            save_jobs = []
            for (entry, folder, page_stem, _), cap in zip(valid, captions):
                new_caps[entry] = cap
                save_jobs.append((folder, page_stem, cap))
            for entry, _, _ in invalid:
                new_caps[entry] = ""

            cpu_saver.submit(_save_captions, save_jobs)

            done = min(batch_start + BATCH_SIZE, total)
            elapsed = time.time() - t_start
            rate = done / elapsed if elapsed > 0 else 1
            log.info(
                f"  Qwen {done:,}/{total:,} | "
                f"{rate:.1f}p/s | 잔여 {(total-done)/rate/60:.1f}분"
            )

    del model
    torch.cuda.empty_cache()
    import gc; gc.collect()
    log.info(f"[Phase1] 완료 ({len(new_caps):,}페이지) -- VRAM 해제")
    return new_caps


# ── Phase 2: BGE-M3 증분 Im 재임베딩 ─────────────────────────────────────────

def phase2_embed(all_ids: list[str], new_caps: dict[str, str]) -> tuple[list[str], list[int], np.ndarray]:
    """변경된 캡션 페이지만 Im 재임베딩. (changed_entries, changed_idx, new_Im_rows) 반환."""
    # 실제로 이전과 달라진 캡션만 선택
    changed_entries: list[str] = []
    changed_indices: list[int] = []
    changed_texts:   list[str] = []

    idx_map = {e: i for i, e in enumerate(all_ids)}
    for entry, new_cap in new_caps.items():
        if not new_cap:
            continue
        idx = idx_map.get(entry)
        if idx is None:
            continue
        changed_entries.append(entry)
        changed_indices.append(idx)
        # Im 소스: page_text가 있으면 우선, 없으면 새 캡션
        parts = entry.split("/")
        pt_path = PT_BASE / parts[1] / f"{Path(parts[2]).stem}.txt"
        if pt_path.exists():
            try:
                pt = pt_path.read_text(encoding="utf-8", errors="replace").strip()
                if len(pt) > 100 and any('가' <= c <= '힣' for c in pt):
                    changed_texts.append(pt + "\n\n" + new_cap)
                    continue
            except Exception:
                pass
        changed_texts.append(new_cap)

    if not changed_entries:
        log.info("[Phase2] 변경 entry 없음 -- 스킵")
        return [], [], np.empty((0, 1024), dtype=np.float32)

    log.info(f"[Phase2] BGE-M3 Im 재임베딩: {len(changed_entries):,}페이지...")
    from embedders.trichef import bgem3_caption_im as im_emb
    new_vecs = im_emb.embed_passage(changed_texts)

    Im = np.load(CACHE / "cache_doc_page_Im.npy").astype(np.float32)
    for arr_idx, vec in zip(changed_indices, new_vecs):
        Im[arr_idx] = vec.astype(np.float32)
    np.save(CACHE / "cache_doc_page_Im.npy", Im)
    log.info("  Im 캐시 저장 완료")

    return changed_entries, changed_indices, Im


# ── Phase 3: ChromaDB 증분 upsert ────────────────────────────────────────────

def phase3_upsert(all_ids: list[str], changed_entries: list[str], changed_indices: list[int], Im: np.ndarray) -> None:
    if not changed_entries:
        log.info("[Phase3] upsert 대상 없음 -- 스킵")
        return
    log.info(f"[Phase3] ChromaDB 증분 upsert: {len(changed_entries):,}페이지...")

    Re = np.load(CACHE / "cache_doc_page_Re.npy").astype(np.float32)
    Z  = np.load(CACHE / "cache_doc_page_Z.npy").astype(np.float32)
    from services.trichef import tri_gs
    from embedders.trichef.incremental_runner import _upsert_chroma
    Im_perp, Z_perp = tri_gs.orthogonalize(Re, Im, Z)

    sub_Re  = Re[changed_indices]
    sub_Im  = Im_perp[changed_indices]
    sub_Z   = Z_perp[changed_indices]
    _upsert_chroma(TRICHEF_CFG["COL_DOC_PAGE"], changed_entries, sub_Re, sub_Im, sub_Z, EXTRACT)

    try:
        from services.chroma_async import drain_and_wait
        drain_and_wait()
    except Exception:
        pass
    log.info("[Phase3] 완료")


# ── Phase 4: lexical 재빌드 ───────────────────────────────────────────────────

def phase4_sparse() -> None:
    from services.trichef import lexical_rebuild
    lexical_rebuild.rebuild_doc_lexical()
    log.info("[Phase4] lexical 재빌드 완료")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=== 확장 캡션 품질 수정 + 증분 Im 재임베딩 ===")
    t0 = time.time()

    with open(IDS_FILE, encoding="utf-8") as f:
        all_ids: list[str] = json.load(f)["ids"]
    log.info(f"총 페이지: {len(all_ids):,}")

    bad_entries = phase0_scan(all_ids)
    if not bad_entries:
        log.info("불량 캡션 없음 -- 종료")
        return

    log.info(f"재캡셔닝 대상: {len(bad_entries):,}페이지")
    # 불량 폴더별 통계 출력
    folder_counts: Counter = Counter()
    for e in bad_entries:
        parts = e.split("/")
        if len(parts) >= 2:
            folder_counts[parts[1]] += 1
    for folder, cnt in folder_counts.most_common(10):
        log.info(f"  {folder}: {cnt}페이지")

    new_caps  = phase1_qwen(bad_entries)
    ch_entries, ch_indices, Im = phase2_embed(all_ids, new_caps)
    phase3_upsert(all_ids, ch_entries, ch_indices, Im)
    if ch_entries:
        phase4_sparse()

    elapsed = (time.time() - t0) / 60
    log.info(f"=== 완료 ({elapsed:.1f}분) -- 수정 {len(ch_entries):,}페이지 ===")


if __name__ == "__main__":
    main()
