"""scripts/repair_doc_im_axis.py — Doc Im 축 전체 재구축.

문제: 34,718 페이지 중 대부분이 영어 오캡션(BLIP)으로 Im 축 임베딩이 무효화됨.
해결:
  Phase 1 (CPU parallel): 각 페이지의 Im 소스 결정
    page_text(>100자 한국어) > 한국어 캡션 > Qwen VL 필요 표시
  Phase 2 (GPU - Qwen VL): 이미지 위주 2,403페이지 캡셔닝
    이미지 프리로드는 CPU ThreadPool, GPU는 Qwen 연속 처리
  Phase 3 (GPU - BGE-M3): 전체 34,718페이지 Im 재임베딩
  Phase 4 (CPU+GPU): Re⊥Im⊥Z 직교화 → ChromaDB upsert → Im 캐시 저장

실행: python scripts/repair_doc_im_axis.py
"""
from __future__ import annotations
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PATHS, TRICHEF_CFG

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger(__name__)

EXTRACT = Path(PATHS["TRICHEF_DOC_EXTRACT"])
CACHE   = Path(PATHS["TRICHEF_DOC_CACHE"])
PT_BASE  = EXTRACT / "page_text"
CAP_BASE = EXTRACT / "captions"
PI_BASE  = EXTRACT / "page_images"
IDS_FILE = CACHE / "doc_page_ids.json"


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _is_english_only(text: str) -> bool:
    return bool(text) and not any("가" <= c <= "힣" for c in text)


def _get_im_source(entry: str) -> tuple[str, str | None]:
    """(entry, im_text | None) 반환. None = Qwen 필요."""
    parts = entry.split("/")
    if len(parts) < 3:
        return entry, ""
    folder, page_file = parts[1], parts[2]
    page_stem = Path(page_file).stem

    pt = PT_BASE / folder / f"{page_stem}.txt"
    if pt.exists():
        try:
            txt = pt.read_text(encoding="utf-8").strip()
            if len(txt) > 100 and any("가" <= c <= "힣" for c in txt):
                return entry, txt
        except Exception:
            pass

    cap = CAP_BASE / folder / f"{page_stem}.txt"
    if cap.exists():
        try:
            c = cap.read_text(encoding="utf-8", errors="replace").strip()
            if c and not _is_english_only(c):
                return entry, c
        except Exception:
            pass

    return entry, None  # Qwen 필요


# ── Phase 1: Im 소스 병렬 결정 (CPU) ─────────────────────────────────────────

def phase1_determine_sources(ids: list[str]) -> tuple[list[str], list[str]]:
    log.info(f"[Phase1] {len(ids):,}페이지 Im 소스 결정 중 (CPU ThreadPool)...")
    texts: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=min(16, os.cpu_count() or 4)) as ex:
        futures = {ex.submit(_get_im_source, e): e for e in ids}
        done = 0
        for fut in as_completed(futures):
            entry, text = fut.result()
            texts[entry] = text
            done += 1
            if done % 5000 == 0:
                log.info(f"  {done:,}/{len(ids):,}")

    need_qwen = [e for e in ids if texts[e] is None]
    log.info(f"[Phase1] page_text/캡션 사용: {len(ids)-len(need_qwen):,} | Qwen 필요: {len(need_qwen):,}")
    return texts, need_qwen


# ── Phase 2: Qwen VL 캡셔닝 (GPU) ───────────────────────────────────────────

def phase2_qwen_caption(need_qwen: list[str], texts: dict) -> None:
    if not need_qwen:
        log.info("[Phase2] Qwen 캡셔닝 불필요 — 스킵")
        return

    log.info(f"[Phase2] Qwen VL 캡셔닝 시작: {len(need_qwen):,}페이지...")

    import sys as _sys
    _DI = Path(__file__).resolve().parents[3] / "DI_TriCHEF"
    if str(_DI) not in _sys.path:
        _sys.path.insert(0, str(_DI))
    from captioner.qwen_vl_ko import QwenKoCaptioner
    from PIL import Image

    qwen = QwenKoCaptioner(dtype="float16")
    qwen._load()

    _PROMPTS = {
        "title":    "이 문서 페이지의 핵심을 1줄로 한국어로 표현하세요.",
        "synopsis": "이 문서 페이지를 한국어로 자세히 묘사하세요. 주요 내용, 그래프, 표, 이미지가 있으면 설명하세요. 3~5문장.",
        "tags_kr":  "이 문서 페이지를 표현하는 한국어 키워드를 10~15개 쉼표로 구분하여 출력하세요.",
    }

    def _caption_page(img_path: Path) -> str:
        try:
            im = Image.open(img_path).convert("RGB")
            parts = {}
            for stage, prompt in _PROMPTS.items():
                parts[stage] = (qwen.caption(im, prompt=prompt,
                                              max_new_tokens=150,
                                              max_image_side=896) or "").strip()
            return " ".join(v for v in parts.values() if v)
        except Exception as e:
            log.warning(f"  Qwen 실패 {img_path.name}: {e}")
            return ""

    # CPU 프리로드 + GPU 처리
    def _load_img(entry: str):
        parts = entry.split("/")
        if len(parts) < 3:
            return entry, None, None
        folder, page_file = parts[1], parts[2]
        img_path = PI_BASE / folder / page_file
        return entry, img_path, folder, Path(page_file).stem

    with ThreadPoolExecutor(max_workers=4) as loader:
        for i, fut in enumerate(loader.map(_load_img, need_qwen)):
            entry, img_path, folder, page_stem = fut
            if img_path is None or not img_path.exists():
                texts[entry] = ""
                continue
            cap_text = _caption_page(img_path)
            texts[entry] = cap_text
            # 캡션 저장 (기존 캡션 폴더에 덮어쓰기)
            if cap_text:
                cap_file = CAP_BASE / folder / f"{page_stem}.txt"
                cap_file.parent.mkdir(parents=True, exist_ok=True)
                try:
                    cap_file.write_text(cap_text, encoding="utf-8")
                except Exception:
                    pass
            if (i + 1) % 100 == 0:
                log.info(f"  Qwen {i+1:,}/{len(need_qwen):,}")

    # Qwen VRAM 해제
    try:
        if hasattr(qwen, "unload"):
            qwen.unload()
        else:
            qwen._model = None
            qwen._processor = None
        import gc, torch
        gc.collect()
        torch.cuda.empty_cache()
    except Exception:
        pass
    log.info("[Phase2] Qwen 캡셔닝 완료 + VRAM 해제")


# ── Phase 3: BGE-M3 Im 재임베딩 (GPU) ───────────────────────────────────────

def phase3_embed_im(ids: list[str], texts: dict) -> np.ndarray:
    log.info(f"[Phase3] BGE-M3 Im 재임베딩: {len(ids):,}페이지...")
    from embedders.trichef import bgem3_caption_im as im_embedder

    captions = [texts.get(e) or "" for e in ids]
    Im = im_embedder.embed_passage(captions)
    log.info(f"[Phase3] Im 임베딩 완료: shape={Im.shape}")
    return Im


# ── Phase 4: 직교화 + ChromaDB upsert + 캐시 저장 ───────────────────────────

def phase4_update_cache(ids: list[str], Im_new: np.ndarray) -> None:
    log.info("[Phase4] Re/Z 캐시 로드 + 직교화...")
    Re = np.load(CACHE / "cache_doc_page_Re.npy").astype(np.float32)
    Z  = np.load(CACHE / "cache_doc_page_Z.npy").astype(np.float32)
    assert Re.shape[0] == len(ids), f"Re rows {Re.shape[0]} != ids {len(ids)}"

    from services.trichef import tri_gs
    Im_perp, Z_perp = tri_gs.orthogonalize(Re, Im_new, Z)

    log.info("[Phase4] Im 캐시 저장...")
    np.save(CACHE / "cache_doc_page_Im.npy", Im_new.astype(np.float32))

    log.info("[Phase4] ChromaDB upsert (전체)...")
    from embedders.trichef.incremental_runner import _upsert_chroma
    _upsert_chroma(
        TRICHEF_CFG["COL_DOC_PAGE"], ids, Re, Im_perp, Z_perp, EXTRACT
    )
    # async 큐 비우기
    try:
        from services.chroma_async import drain_and_wait
        drain_and_wait()
    except Exception:
        pass

    log.info("[Phase4] 완료")


# ── Phase 5: sparse/lexical 재빌드 ───────────────────────────────────────────

def phase5_rebuild_sparse() -> None:
    log.info("[Phase5] sparse/lexical 재빌드...")
    try:
        from services.trichef import lexical_rebuild
        lexical_rebuild.rebuild_doc_lexical()
        log.info("[Phase5] 완료")
    except Exception as e:
        log.warning(f"[Phase5] 실패: {e}")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=== Doc Im 축 전체 재구축 시작 ===")

    with open(IDS_FILE, encoding="utf-8") as f:
        ids: list[str] = json.load(f)["ids"]
    log.info(f"총 페이지: {len(ids):,}")

    texts, need_qwen = phase1_determine_sources(ids)
    phase2_qwen_caption(need_qwen, texts)
    Im_new = phase3_embed_im(ids, texts)
    phase4_update_cache(ids, Im_new)
    phase5_rebuild_sparse()

    log.info("=== Doc Im 축 재구축 완료 ===")


if __name__ == "__main__":
    main()
