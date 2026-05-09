"""scripts/repair_caption_quality.py — 불량 캡션 탐지·수정 + 증분 Im 재임베딩

문제:
  1) '1.1.1.1.1...' 소수점 반복 패턴 (PDF 목차 추출 오류)
  2) 동일 문장 3회 이상 반복 (Qwen hallucination)

처리:
  Phase 0: 전체 caption 파일 스캔 → 불량 파일 목록 수집
  Phase 1: 불량 캡션 정제 후 파일 덮어쓰기
  Phase 2: 해당 페이지만 BGE-M3 증분 Im 재임베딩
  Phase 3: Im 캐시 업데이트 + ChromaDB 증분 upsert
  Phase 4: lexical 재빌드 (변경 페이지 있을 경우)
"""
from __future__ import annotations
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PATHS, TRICHEF_CFG

LOG_FILE = Path(PATHS["DATA_ROOT"]).parent / "logs" / "repair_caption_quality.log"
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
IDS_FILE = CACHE / "doc_page_ids.json"

CPU_WORKERS = 8


# ── 캡션 클리닝 ────────────────────────────────────────────────────────────────

def _clean_caption(text: str) -> str:
    """소수점 반복·문장 중복 제거."""
    if not text:
        return text
    # 1) 소수점 반복 제거 (1.1.1.1...)
    cleaned = re.sub(r'(\b\d+\.\d+\.){3,}', '', text)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    # 2) 줄 단위 중복 제거 (3회 이상)
    lines = [l.strip() for l in re.split(r'[\n。]', cleaned) if l.strip()]
    seen: dict[str, int] = {}
    deduped: list[str] = []
    for line in lines:
        cnt = seen.get(line, 0)
        seen[line] = cnt + 1
        if cnt < 2:
            deduped.append(line)
    result = '\n'.join(deduped)
    return result if result else text


def _is_bad_caption(text: str) -> bool:
    """불량 캡션 여부 판별."""
    if not text:
        return False
    # 소수점 반복 패턴
    if re.search(r'(\b\d+\.\d+\.){3,}', text):
        return True
    # 동일 줄 3회 이상 반복
    lines = [l.strip() for l in re.split(r'[\n。]', text) if l.strip()]
    from collections import Counter
    counts = Counter(lines)
    if any(v >= 3 for v in counts.values()):
        return True
    return False


# ── Phase 0: 불량 캡션 스캔 ───────────────────────────────────────────────────

def _scan_one(cap_file: Path) -> tuple[Path, bool, str]:
    try:
        text = cap_file.read_text(encoding="utf-8", errors="replace").strip()
        return cap_file, _is_bad_caption(text), text
    except Exception:
        return cap_file, False, ""


def phase0_scan() -> list[tuple[Path, str]]:
    """전체 caption 파일 스캔 → 불량 (cap_file, original_text) 목록 반환."""
    all_caps = list(CAP_BASE.rglob("*.txt"))
    log.info(f"[Phase0] 캡션 파일 스캔: {len(all_caps):,}개...")
    t0 = time.time()
    bad: list[tuple[Path, str]] = []
    with ThreadPoolExecutor(max_workers=CPU_WORKERS) as ex:
        for cap_file, is_bad, text in ex.map(_scan_one, all_caps):
            if is_bad:
                bad.append((cap_file, text))
    log.info(f"[Phase0] 완료 ({time.time()-t0:.1f}s) — 불량 {len(bad):,} / 전체 {len(all_caps):,}")
    return bad


# ── Phase 1: 캡션 정제 + 파일 덮어쓰기 ──────────────────────────────────────

def phase1_fix(bad_caps: list[tuple[Path, str]]) -> list[Path]:
    """불량 캡션 정제 후 저장. 수정된 파일 목록 반환."""
    fixed: list[Path] = []
    for cap_file, orig in bad_caps:
        cleaned = _clean_caption(orig)
        if cleaned != orig and cleaned:
            try:
                cap_file.write_text(cleaned, encoding="utf-8")
                fixed.append(cap_file)
            except Exception as e:
                log.warning(f"  저장 실패 {cap_file.name}: {e}")
    log.info(f"[Phase1] 캡션 정제 완료: {len(fixed):,}개 수정")
    return fixed


# ── entry→index 매핑 ─────────────────────────────────────────────────────────

def _build_entry_index(all_ids: list[str]) -> dict[str, int]:
    return {e: i for i, e in enumerate(all_ids)}


def _cap_file_to_entries(cap_file: Path, all_ids: list[str]) -> list[str]:
    """캡션 파일 경로 → 관련 entry 목록 (folder/page_stem 기준)."""
    # cap_file 예: CAP_BASE / folder / page_stem.txt
    folder = cap_file.parent.name
    stem   = cap_file.stem
    # entry 형식: "doc_page/{folder}/{stem}.png" or similar
    matches = [e for e in all_ids
               if f"/{folder}/" in e and Path(e.split("/")[-1]).stem == stem]
    return matches


# ── Phase 2~3: 증분 Im 재임베딩 + ChromaDB upsert ────────────────────────────

def phase2_embed_and_upsert(fixed_caps: list[Path], all_ids: list[str]) -> int:
    """수정된 캡션 파일 → 해당 페이지 Im 재임베딩 → 캐시·ChromaDB 업데이트."""
    if not fixed_caps:
        log.info("[Phase2] 수정 파일 없음 — 스킵")
        return 0

    idx_map = _build_entry_index(all_ids)

    # 수정 캡션 → entry 매핑
    changed: dict[str, str] = {}  # entry → new_caption_text
    for cap_file in fixed_caps:
        entries = _cap_file_to_entries(cap_file, all_ids)
        try:
            new_text = cap_file.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            continue
        for e in entries:
            changed[e] = new_text

    if not changed:
        log.info("[Phase2] 매핑된 entry 없음 — 스킵")
        return 0

    log.info(f"[Phase2] BGE-M3 증분 Im 재임베딩: {len(changed):,}페이지...")
    from embedders.trichef import bgem3_caption_im as im_emb

    changed_entries = list(changed.keys())
    changed_texts   = [changed[e] for e in changed_entries]
    changed_indices = [idx_map[e] for e in changed_entries if e in idx_map]

    new_vecs = im_emb.embed_passage(changed_texts)
    Im = np.load(CACHE / "cache_doc_page_Im.npy").astype(np.float32)
    for arr_idx, new_vec in zip(changed_indices, new_vecs):
        Im[arr_idx] = new_vec.astype(np.float32)

    Re = np.load(CACHE / "cache_doc_page_Re.npy").astype(np.float32)
    Z  = np.load(CACHE / "cache_doc_page_Z.npy").astype(np.float32)
    from services.trichef import tri_gs
    from embedders.trichef.incremental_runner import _upsert_chroma
    Im_perp, Z_perp = tri_gs.orthogonalize(Re, Im, Z)

    np.save(CACHE / "cache_doc_page_Im.npy", Im)
    log.info("  Im 캐시 저장 완료")

    sub_ids = [all_ids[i] for i in changed_indices]
    sub_Re  = Re[changed_indices]
    sub_Im  = Im_perp[changed_indices]
    sub_Z   = Z_perp[changed_indices]
    _upsert_chroma(TRICHEF_CFG["COL_DOC_PAGE"], sub_ids, sub_Re, sub_Im, sub_Z, EXTRACT)

    try:
        from services.chroma_async import drain_and_wait
        drain_and_wait()
    except Exception:
        pass

    log.info(f"[Phase2] 완료: {len(changed):,}페이지 Im 재임베딩·upsert")
    return len(changed)


# ── Phase 3: lexical 재빌드 ───────────────────────────────────────────────────

def phase3_sparse() -> None:
    from services.trichef import lexical_rebuild
    lexical_rebuild.rebuild_doc_lexical()
    log.info("[Phase3] lexical 재빌드 완료")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=== Doc 캡션 품질 수정 + 증분 Im 재임베딩 ===")
    t0 = time.time()

    with open(IDS_FILE, encoding="utf-8") as f:
        all_ids: list[str] = json.load(f)["ids"]
    log.info(f"총 페이지: {len(all_ids):,}")

    bad_caps  = phase0_scan()
    fixed     = phase1_fix(bad_caps)
    n_changed = phase2_embed_and_upsert(fixed, all_ids)
    if n_changed > 0:
        phase3_sparse()

    log.info(f"=== 완료 ({(time.time()-t0)/60:.1f}분) — 수정 {n_changed:,}페이지 ===")


if __name__ == "__main__":
    main()
