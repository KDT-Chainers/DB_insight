"""embedders/trichef/incremental_runner.py — 증분 임베딩 러너.

IndexRegistry 에 저장된 파일 SHA-256 해시를 비교하여 신규/수정 파일만 임베딩한다.
3축 캐시 (.npy) 누적 append + ChromaDB upsert + calibration 재보정 트리거.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import chromadb
import numpy as np
from chromadb.config import Settings
from tqdm import tqdm

from config import PATHS, TRICHEF_CFG
from embedders.trichef import siglip2_re, dinov2_z, qwen_caption, doc_page_render
from embedders.trichef import bgem3_caption_im as im_embedder  # v2 P1: e5→BGE-M3
from embedders.trichef import blip_caption_triple, doc_ingest  # v2 P1 Phase B (doc_ingest 공용 유지)
from services.trichef import tri_gs
from services.trichef.prune import prune_domain
from services.trichef import lexical_rebuild

logger = logging.getLogger(__name__)


# W4-B: BLIP 영어 캡셔너 → Qwen2-VL 한국어 캡셔너 교체. lazy 싱글톤.
_QWEN_CAPTIONER = None
def _get_qwen_captioner():
    global _QWEN_CAPTIONER
    if _QWEN_CAPTIONER is None:
        import sys
        from pathlib import Path as _P
        _DI_ROOT = _P(__file__).resolve().parents[4] / "DI_TriCHEF"
        if str(_DI_ROOT) not in sys.path:
            sys.path.insert(0, str(_DI_ROOT))
        from captioner.qwen_vl_ko import QwenKoCaptioner
        _QWEN_CAPTIONER = QwenKoCaptioner(dtype="float16")
    return _QWEN_CAPTIONER


def _caption_for_im(cap_dir: Path, img_path: Path, key: str | None = None) -> str:
    """캡션 로드/생성 우선순위:
      1) `<hash_stem>.caption.json` (레거시 BLIP L1/L2/L3)
      2) `<hash_stem>.txt`
      3) `<plain_stem>.txt` (Qwen 재캡션 결과 — W4-B fallback)
      4) 없으면 Qwen2-VL 로 신규 한국어 캡션 생성 → plain_stem `.txt` 저장
    """
    stem = doc_page_render.stem_key_for(key) if key else img_path.stem
    plain = img_path.stem
    jp = cap_dir / f"{stem}.caption.json"
    tp = cap_dir / f"{stem}.txt"
    plain_tp = cap_dir / f"{plain}.txt"
    if jp.exists():
        try:
            d = json.loads(jp.read_text(encoding="utf-8"))
            txt = d.get("L3") or d.get("L1") or ""
            if txt:
                return txt
        except Exception:
            pass
    if tp.exists():
        t = tp.read_text(encoding="utf-8").strip()
        if t:
            return t
    if plain_tp.exists():
        t = plain_tp.read_text(encoding="utf-8").strip()
        if t:
            return t
    # 신규: Qwen 한국어 캡션 생성
    try:
        from PIL import Image
        im = Image.open(img_path).convert("RGB")
        text = _get_qwen_captioner().caption(im, max_new_tokens=60, max_image_side=896)
    except Exception as e:
        logger.warning(f"[caption] Qwen 캡션 실패 {img_path.name}: {type(e).__name__}: {e}")
        text = ""
        # [P1.5] 실패 파일 추적용 append-only ledger — 추후 재처리 스크립트에서 활용.
        try:
            ledger = cap_dir / "_caption_failures.jsonl"
            ledger.parent.mkdir(parents=True, exist_ok=True)
            import time as _t
            with ledger.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts":       _t.strftime("%Y-%m-%d %H:%M:%S"),
                    "img":      str(img_path),
                    "key":      key,
                    "stem":     stem,
                    "err_type": type(e).__name__,
                    "err_msg":  str(e)[:500],
                }, ensure_ascii=False) + "\n")
        except Exception:  # ledger 실패는 본류에 영향 주지 않음
            pass
    # plain stem 에 저장 (recaption_all / fix_non_korean 과 동일 규약)
    if text:
        plain_tp.write_text(text, encoding="utf-8")
        (cap_dir / f"{plain}.qwen").write_text("", encoding="utf-8")
    return text


@dataclass
class IncrementalResult:
    domain: str
    new: int
    existing: int
    total: int


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_registry(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_registry(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_trichef_collection(name: str):
    """TRI-CHEF 전용 ChromaDB 컬렉션 반환 (3200d concat 벡터용)."""
    chroma_path = Path(PATHS["TRICHEF_CHROMA"])
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(chroma_path),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def _upsert_chroma(collection: str, ids: list[str],
                   Re: np.ndarray, Im_perp: np.ndarray, Z_perp: np.ndarray,
                   src_root: Path) -> None:
    """ChromaDB 에 Re||Im⊥||Z⊥⊥ concat 벡터로 upsert.

    ChromaDB 는 빠른 prefilter 용으로만 사용.
    메인 점수는 .npy 원본으로 Hermitian 계산.
    """
    col = _get_trichef_collection(collection)
    metadatas = [{"path": str(src_root / i), "id": i} for i in ids]
    embeds = np.hstack([Re, Im_perp, Z_perp]).astype(np.float32)
    CHUNK = 5000  # ChromaDB max batch size ~5461
    for start in range(0, len(ids), CHUNK):
        end = start + CHUNK
        col.upsert(
            ids=ids[start:end],
            embeddings=embeds[start:end].tolist(),
            metadatas=metadatas[start:end],
        )


def _purge_doc_page_cache(keys: set[str], cache_dir: Path) -> int:
    """삭제/수정된 doc rel_key 들의 page_images/captions/ids.json/.npy/Chroma 정리.

    stem_key_for(key) 기준으로 page_images/<stem_key>, captions/<stem_key> 디렉토리를
    삭제하고, 해당 prefix 를 가진 ids.json 행을 .npy 3축과 동시 필터링한다.
    ChromaDB 도 삭제.
    """
    import shutil
    if not keys:
        return 0
    stem_keys = {doc_page_render.stem_key_for(k) for k in keys}
    extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])

    # 1) 디렉토리 삭제 (페이지 이미지 + 캡션)
    for sk in stem_keys:
        shutil.rmtree(doc_page_render.PAGE_DIR / sk, ignore_errors=True)
        shutil.rmtree(extract / "captions" / sk, ignore_errors=True)

    # 2) ids.json + .npy rows 필터링
    ids_path = cache_dir / "doc_page_ids.json"
    if not ids_path.exists():
        return 0
    ids = json.loads(ids_path.read_text(encoding="utf-8")).get("ids", [])
    to_remove_ids: list[str] = []
    keep_mask = np.ones(len(ids), dtype=bool)
    for idx, i in enumerate(ids):
        parts = Path(i).parts
        if len(parts) >= 3 and parts[0] == "page_images" and parts[1] in stem_keys:
            keep_mask[idx] = False
            to_remove_ids.append(i)
    removed = int((~keep_mask).sum())
    if removed == 0:
        return 0

    for base in ("cache_doc_page_Re", "cache_doc_page_Im", "cache_doc_page_Z"):
        pth = cache_dir / f"{base}.npy"
        if pth.exists():
            arr = np.load(pth)
            if arr.shape[0] == len(ids):
                np.save(pth, arr[keep_mask])
            else:
                logger.warning(f"[purge] {pth.name} 행 수 불일치({arr.shape[0]} vs {len(ids)}) → 건너뜀")

    # sparse.npz + asf_token_sets.json 도 동시 필터 (후속 rebuild 미호출 대비)
    sparse_path = cache_dir / "cache_doc_page_sparse.npz"
    if sparse_path.exists():
        try:
            from scipy import sparse as _sp
            mat = _sp.load_npz(sparse_path)
            if mat.shape[0] == len(ids):
                _sp.save_npz(sparse_path, mat[keep_mask])
        except Exception as e:
            logger.warning(f"[purge] sparse 필터 실패: {e}")
    asf_path = cache_dir / "asf_token_sets.json"
    if asf_path.exists():
        try:
            asf = json.loads(asf_path.read_text(encoding="utf-8"))
            if isinstance(asf, list) and len(asf) == len(ids):
                new_asf = [s for s, k in zip(asf, keep_mask) if k]
                asf_path.write_text(json.dumps(new_asf, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"[purge] asf_token_sets 필터 실패: {e}")

    kept_ids = [i for i, k in zip(ids, keep_mask) if k]
    ids_path.write_text(json.dumps({"ids": kept_ids}, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # 3) ChromaDB 삭제
    try:
        col = _get_trichef_collection(TRICHEF_CFG["COL_DOC_PAGE"])
        CHUNK = 2000
        for s in range(0, len(to_remove_ids), CHUNK):
            col.delete(ids=to_remove_ids[s:s+CHUNK])
    except Exception as e:
        logger.warning(f"[purge] Chroma 삭제 실패: {e}")

    logger.info(f"[purge:doc_page] {len(stem_keys)}개 stem_key, rows {removed}개 제거")
    return removed


# ── 이미지 도메인 ────────────────────────────────────────────────────────────
def run_image_incremental() -> IncrementalResult:
    raw_dir   = Path(PATHS["RAW_DB"]) / "Img"
    cache_dir = Path(PATHS["TRICHEF_IMG_CACHE"])
    reg_path  = cache_dir / "registry.json"
    registry  = _load_registry(reg_path)

    img_files = sorted(
        p for p in raw_dir.rglob("*")
        if p.suffix.lower() in IMAGE_EMBED_EXTS
    )
    # v2 P1: stale 정리
    current_keys = {str(p.relative_to(raw_dir)).replace("\\", "/") for p in img_files}
    registry, pruned = prune_domain(
        "image", raw_dir, cache_dir, registry, current_keys,
        npy_bases=["cache_img_Re_siglip2", "cache_img_Im_e5cap", "cache_img_Z_dinov2"],
        ids_filename="img_ids.json",
        col_name=TRICHEF_CFG["COL_IMAGE"],
    )
    if pruned:
        _save_registry(reg_path, registry)
    existing_count = len(registry)
    new_files: list[Path] = []
    for p in img_files:
        key = str(p.relative_to(raw_dir)).replace("\\", "/")
        sha = _sha256(p)
        if registry.get(key, {}).get("sha") != sha:
            new_files.append(p)
            registry[key] = {"sha": sha, "abs": str(p)}

    logger.info(f"[img_inc] 기존={existing_count}, 신규={len(new_files)}")
    if not new_files:
        return IncrementalResult("image", 0, existing_count, existing_count)

    # 1. 캡션 생성 (Im 축 원천)
    cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    cap_dir.mkdir(parents=True, exist_ok=True)
    captions: list[str] = []
    for p in tqdm(new_files, desc="BLIP caption"):
        key = str(p.relative_to(raw_dir)).replace("\\", "/")
        captions.append(_caption_for_im(cap_dir, p, key))

    # 2. 3축 임베딩
    new_Re = siglip2_re.embed_images(new_files)
    new_Im = im_embedder.embed_passage(captions)
    new_Z  = dinov2_z.embed_images(new_files)

    # 3. [P2B.2] replace-by-file: 동일 파일 재인덱싱 시 stale 행 제거 후 교체
    from . import cache_ops as _co
    new_ids  = [str(p.relative_to(raw_dir)).replace("\\", "/") for p in new_files]
    _res = _co.replace_by_file(
        cache_dir=cache_dir,
        file_keys=new_ids,
        arrays={
            "cache_img_Re_siglip2.npy": new_Re,
            "cache_img_Im_e5cap.npy":   new_Im,
            "cache_img_Z_dinov2.npy":   new_Z,
        },
        new_ids=new_ids,
        ids_file="img_ids.json",
    )
    Re_all = _res["merged"]["cache_img_Re_siglip2.npy"]
    Im_all = _res["merged"]["cache_img_Im_e5cap.npy"]
    Z_all  = _res["merged"]["cache_img_Z_dinov2.npy"]
    all_ids = _res["ids"]

    # 4. Gram-Schmidt 직교화 + ChromaDB upsert
    Im_perp, Z_perp = tri_gs.orthogonalize(Re_all, Im_all, Z_all)
    _upsert_chroma(TRICHEF_CFG["COL_IMAGE"], all_ids, Re_all, Im_perp, Z_perp, raw_dir)

    # 5. lexical 채널 재빌드 (vocab / asf_token_sets / sparse) — 신규 항목 반영 필수
    try:
        lexical_rebuild.rebuild_image_lexical()
    except Exception as e:
        logger.exception(f"[image] lexical rebuild 실패: {e}")

    # 6. calibration 재보정 (W4-5: cross-modal 자동 훅)
    try:
        from services.trichef import calibration as _cal
        from embedders.trichef.caption_io import load_caption as _load_cap
        caps = []
        for i in all_ids:
            t = _load_cap(cap_dir, doc_page_render.stem_key_for(i))
            if not t: t = _load_cap(cap_dir, Path(i).stem)
            caps.append(t)
        info = _cal.calibrate_image_crossmodal(caps, Re_all, Im_perp, Z_perp,
                                                sample_q=200, pairs_per_q=5)
        logger.info(f"[image] crossmodal calibration: mu={info['mu_null']:.4f} "
                    f"sig={info['sigma_null']:.4f} thr={info['abs_threshold']:.4f}")
    except Exception as e:
        logger.exception(f"[image] calibration 실패: {e}")

    # 7. registry save
    _save_registry(reg_path, registry)

    return IncrementalResult("image", len(new_files), existing_count, len(all_ids))


# ── 문서 도메인 (doc_page) ──────────────────────────────────────────────────
def run_doc_incremental() -> IncrementalResult:
    raw_dir = Path(PATHS["RAW_DB"]) / "Doc"
    cache_dir = Path(PATHS["TRICHEF_DOC_CACHE"])
    reg_path  = cache_dir / "registry.json"
    registry  = _load_registry(reg_path)

    # v2 P1 Phase B: doc_ingest 지원 확장자 전체 (SSOT: _extensions.DOC_EXTS via DOC_EMBED_EXTS)
    doc_files = sorted(
        p for p in raw_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in DOC_EMBED_EXTS
    )
    current_keys = {str(p.relative_to(raw_dir)).replace("\\", "/") for p in doc_files}
    stale = set(registry.keys()) - current_keys

    sha_cache: dict[str, str] = {}
    new_docs: list[Path] = []
    modified_keys: set[str] = set()  # SHA 변경된 기존 파일 (캐시 stale 대상)
    for p in doc_files:
        key = str(p.relative_to(raw_dir)).replace("\\", "/")
        sha = _sha256(p)
        sha_cache[key] = sha
        if registry.get(key, {}).get("sha") != sha:
            new_docs.append(p)
            if key in registry:
                modified_keys.add(key)
    logger.info(f"[doc_inc] 기존={len(registry)}, 신규={len(new_docs)}, "
                f"수정={len(modified_keys)}, 삭제={len(stale)}")

    # stale(삭제) + modified(SHA 변경) 의 구 page 데이터 통합 정리
    _purge_keys = stale | modified_keys
    if _purge_keys:
        _purge_doc_page_cache(_purge_keys, cache_dir)
        for k in stale:
            registry.pop(k, None)
        _save_registry(reg_path, registry)

    if not new_docs:
        return IncrementalResult("document", 0, len(registry), len(registry))

    # 1. doc_ingest → 페이지 이미지 + 캡션 (PDF/Office/HWP/텍스트 통합)
    IMG_PAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
    all_page_imgs: list[Path] = []
    all_page_captions: list[str] = []
    ingested_docs: list[Path] = []  # 실제 페이지를 기여한 문서만 registry 등록
    skipped_docs: list[Path] = []
    for p in tqdm(new_docs, desc="doc_ingest + caption"):
        rel_key = str(p.relative_to(raw_dir)).replace("\\", "/")
        stem_key = doc_page_render.stem_key_for(rel_key)
        pages = doc_ingest.to_pages(p, stem_key=stem_key)
        img_pages = [pg for pg in pages if pg.suffix.lower() in IMG_PAGE_EXTS]
        if not img_pages:
            skipped_docs.append(p)
            continue
        cap_dir = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "captions" / stem_key
        cap_dir.mkdir(parents=True, exist_ok=True)
        for pg in img_pages:
            all_page_imgs.append(pg)
            all_page_captions.append(_caption_for_im(cap_dir, pg))
        ingested_docs.append(p)

    logger.info(f"[doc_inc] 처리 성공 {len(ingested_docs)}, 스킵 {len(skipped_docs)} "
                f"(LibreOffice 미설치/빈 파일 등)")

    if not all_page_imgs:
        return IncrementalResult("document", 0, len(registry), len(registry))

    # 2. 3축 임베딩 (doc_page)
    new_Re = siglip2_re.embed_images(all_page_imgs)
    new_Im = im_embedder.embed_passage(all_page_captions)
    new_Z  = dinov2_z.embed_images(all_page_imgs)

    # 3. [P2B.2] replace-by-file: 재인덱싱 문서의 기존 page 행 제거 후 교체
    from . import cache_ops as _co
    new_ids = [
        str(pg.relative_to(Path(PATHS["TRICHEF_DOC_EXTRACT"]))).replace("\\", "/")
        for pg in all_page_imgs
    ]
    _res = _co.replace_by_file(
        cache_dir=cache_dir,
        file_keys=new_ids,
        arrays={
            "cache_doc_page_Re.npy": new_Re,
            "cache_doc_page_Im.npy": new_Im,
            "cache_doc_page_Z.npy":  new_Z,
        },
        new_ids=new_ids,
        ids_file="doc_page_ids.json",
    )
    Re_all = _res["merged"]["cache_doc_page_Re.npy"]
    Im_all = _res["merged"]["cache_doc_page_Im.npy"]
    Z_all  = _res["merged"]["cache_doc_page_Z.npy"]
    all_ids = _res["ids"]

    Im_perp, Z_perp = tri_gs.orthogonalize(Re_all, Im_all, Z_all)
    _upsert_chroma(TRICHEF_CFG["COL_DOC_PAGE"], all_ids, Re_all, Im_perp, Z_perp,
                   Path(PATHS["TRICHEF_DOC_EXTRACT"]))

    # 5. registry save — 실제로 페이지를 기여한 문서만 등록 (lexical_rebuild 이전에 커밋)
    for p in ingested_docs:
        key = str(p.relative_to(raw_dir)).replace("\\", "/")
        registry[key] = {"sha": sha_cache[key], "abs": str(p)}
    _save_registry(reg_path, registry)

    # 6. lexical 채널 재빌드 (vocab / asf_token_sets / sparse) — 신규 항목 반영 필수
    #    registry 를 먼저 저장해야 _resolve_doc_pdf_map 이 최신 상태를 읽는다.
    try:
        lexical_rebuild.rebuild_doc_lexical()
    except Exception as e:
        logger.exception(f"[doc_page] lexical rebuild 실패: {e}")

    # [W5-3 ROLLBACK 2026-04-24] doc_page 에 crossmodal_v1 적용 실측 결과:
    #   thr 0.205 → 0.355 (+73%) 로 인해 실제 쿼리 4/4 가 0 hits 로 무너졌다.
    #   caption-pseudo-query 가 같은 문서의 다른 페이지와도 높은 점수를 받아
    #   μ_null/σ_null 이 cross-modal 이 아닌 within-doc 분포로 편향된다.
    #   Doc 스케일(34170 페이지)에서는 random_query_null_v2 가 더 안정적이다.
    logger.info("[doc_page] calibration skipped — use scripts/recalibrate_query_null.py "
                "for random_query_null_v2")

    return IncrementalResult("document", len(ingested_docs), len(registry), len(registry))


# ── 단일 파일 임베딩 (UI 인덱싱 진입점) ────────────────────────────────────

from _extensions import IMAGE_EMBED_EXTS, DOC_EXTS as DOC_EMBED_EXTS


def embed_image_file(file_path: str, progress_cb=None) -> dict:
    """
    단일 이미지 파일 TRI-CHEF 3축 임베딩.
    파일을 raw_DB/Img/staged/ 에 하드링크(실패 시 복사)로 스테이징 후
    기존 TRI-CHEF 파이프라인(캡션→임베딩→GS직교화→ChromaDB)을 수행한다.

    progress_cb(step, total, detail) → bool(True=중단)
      step 1/3: BLIP 캡션
      step 2/3: 3축 임베딩
      step 3/3: 벡터DB 저장
    """
    import os, shutil

    p = Path(file_path)
    if not p.is_file():
        return {"status": "error", "reason": "파일이 존재하지 않습니다"}
    if p.suffix.lower() not in IMAGE_EMBED_EXTS:
        return {"status": "skipped", "reason": f"지원하지 않는 이미지 형식: {p.suffix}"}

    raw_dir   = Path(PATHS["RAW_DB"]) / "Img"
    cache_dir = Path(PATHS["TRICHEF_IMG_CACHE"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    reg_path  = cache_dir / "registry.json"
    registry  = _load_registry(reg_path)

    sha       = _sha256(p)
    stage_rel = Path("staged") / sha[:8] / p.name      # 상대 key
    staged    = raw_dir / stage_rel
    staged.parent.mkdir(parents=True, exist_ok=True)

    key = str(stage_rel).replace("\\", "/")             # "staged/abcd1234/foo.jpg"

    # 이미 인덱싱 완료
    if registry.get(key, {}).get("sha") == sha:
        return {"status": "skipped", "reason": "이미 인덱싱된 파일"}

    # 스테이징 (하드링크 → 실패 시 복사)
    if not staged.exists():
        try:
            os.link(str(p), str(staged))
        except (OSError, NotImplementedError):
            shutil.copy2(str(p), str(staged))

    # ── Step 1/3: BLIP 캡션 ─────────────────────────────
    if progress_cb:
        if progress_cb(1, 3, "BLIP 캡션 생성 중"):
            return {"status": "skipped", "reason": "사용자 중단"}

    cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    cap_dir.mkdir(parents=True, exist_ok=True)
    caption = _caption_for_im(cap_dir, staged, key)

    # ── Step 2/3: 3축 임베딩 ─────────────────────────────
    if progress_cb:
        if progress_cb(2, 3, "3축 임베딩 생성 중 (Re·Im·Z)"):
            return {"status": "skipped", "reason": "사용자 중단"}

    new_Re = siglip2_re.embed_images([staged])
    new_Im = im_embedder.embed_passage([caption])
    new_Z  = dinov2_z.embed_images([staged])

    # [P2B.2] replace-by-file
    from . import cache_ops as _co
    _res = _co.replace_by_file(
        cache_dir=cache_dir,
        file_keys=[key],
        arrays={
            "cache_img_Re_siglip2.npy": new_Re,
            "cache_img_Im_e5cap.npy":   new_Im,
            "cache_img_Z_dinov2.npy":   new_Z,
        },
        new_ids=[key],
        ids_file="img_ids.json",
    )
    Re_all = _res["merged"]["cache_img_Re_siglip2.npy"]
    Im_all = _res["merged"]["cache_img_Im_e5cap.npy"]
    Z_all  = _res["merged"]["cache_img_Z_dinov2.npy"]
    all_ids = _res["ids"]

    # ── Step 3/3: GS 직교화 + ChromaDB 저장 ─────────────
    if progress_cb:
        if progress_cb(3, 3, "벡터DB 저장 중"):
            return {"status": "skipped", "reason": "사용자 중단"}

    Im_perp, Z_perp = tri_gs.orthogonalize(Re_all, Im_all, Z_all)
    _upsert_chroma(TRICHEF_CFG["COL_IMAGE"], all_ids, Re_all, Im_perp, Z_perp, raw_dir)

    try:
        lexical_rebuild.rebuild_image_lexical()
    except Exception as e:
        logger.warning(f"[embed_image_file] lexical rebuild 실패: {e}")

    registry[key] = {"sha": sha, "abs": str(p), "staged": str(staged)}
    _save_registry(reg_path, registry)

    return {"status": "done", "chunks": 1}


def embed_doc_file(file_path: str, progress_cb=None) -> dict:
    """
    단일 문서 파일 TRI-CHEF 3축 임베딩 (페이지 렌더링 포함).
    파일을 raw_DB/Doc/staged/ 에 스테이징 후 기존 파이프라인 실행.

    progress_cb(step, total, detail) → bool(True=중단)
      step 1/3: 문서 페이지 렌더링 + BLIP 캡션
      step 2/3: 3축 임베딩
      step 3/3: 벡터DB 저장
    """
    import os, shutil

    p = Path(file_path)
    if not p.is_file():
        return {"status": "error", "reason": "파일이 존재하지 않습니다"}
    if p.suffix.lower() not in DOC_EMBED_EXTS:
        return {"status": "skipped", "reason": f"지원하지 않는 문서 형식: {p.suffix}"}

    raw_dir   = Path(PATHS["RAW_DB"]) / "Doc"
    cache_dir = Path(PATHS["TRICHEF_DOC_CACHE"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    reg_path  = cache_dir / "registry.json"
    registry  = _load_registry(reg_path)

    sha       = _sha256(p)
    stage_rel = Path("staged") / sha[:8] / p.name
    staged    = raw_dir / stage_rel
    staged.parent.mkdir(parents=True, exist_ok=True)

    key = str(stage_rel).replace("\\", "/")             # "staged/abcd1234/foo.pdf"

    if registry.get(key, {}).get("sha") == sha:
        return {"status": "skipped", "reason": "이미 인덱싱된 파일"}

    if not staged.exists():
        try:
            os.link(str(p), str(staged))
        except (OSError, NotImplementedError):
            shutil.copy2(str(p), str(staged))

    # ── Step 1/3: 페이지 렌더링 + 캡션 ──────────────────
    if progress_cb:
        if progress_cb(1, 3, "문서 페이지 렌더링 + 캡션 생성 중"):
            return {"status": "skipped", "reason": "사용자 중단"}

    stem_key = doc_page_render.stem_key_for(key)
    IMG_PAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
    pages = doc_ingest.to_pages(staged, stem_key=stem_key)
    img_pages = [pg for pg in pages if pg.suffix.lower() in IMG_PAGE_EXTS]
    if not img_pages:
        return {"status": "skipped", "reason": "페이지 이미지 생성 실패 (LibreOffice 필요 또는 빈 파일)"}

    cap_dir = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "captions" / stem_key
    cap_dir.mkdir(parents=True, exist_ok=True)
    captions = [_caption_for_im(cap_dir, pg) for pg in img_pages]

    # ── Step 2/3: 3축 임베딩 ─────────────────────────────
    if progress_cb:
        if progress_cb(2, 3, f"3축 임베딩 ({len(img_pages)}페이지)"):
            return {"status": "skipped", "reason": "사용자 중단"}

    new_Re = siglip2_re.embed_images(img_pages)
    new_Im = im_embedder.embed_passage(captions)
    new_Z  = dinov2_z.embed_images(img_pages)

    # [P2B.2] replace-by-file
    from . import cache_ops as _co
    doc_extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])
    new_page_ids = [
        str(pg.relative_to(doc_extract)).replace("\\", "/")
        for pg in img_pages
    ]
    _res = _co.replace_by_file(
        cache_dir=cache_dir,
        file_keys=new_page_ids,
        arrays={
            "cache_doc_page_Re.npy": new_Re,
            "cache_doc_page_Im.npy": new_Im,
            "cache_doc_page_Z.npy":  new_Z,
        },
        new_ids=new_page_ids,
        ids_file="doc_page_ids.json",
    )
    Re_all = _res["merged"]["cache_doc_page_Re.npy"]
    Im_all = _res["merged"]["cache_doc_page_Im.npy"]
    Z_all  = _res["merged"]["cache_doc_page_Z.npy"]
    all_ids = _res["ids"]

    # ── Step 3/3: GS 직교화 + ChromaDB 저장 ─────────────
    if progress_cb:
        if progress_cb(3, 3, "벡터DB 저장 중"):
            return {"status": "skipped", "reason": "사용자 중단"}

    Im_perp, Z_perp = tri_gs.orthogonalize(Re_all, Im_all, Z_all)
    _upsert_chroma(TRICHEF_CFG["COL_DOC_PAGE"], all_ids, Re_all, Im_perp, Z_perp,
                   doc_extract)

    try:
        lexical_rebuild.rebuild_doc_lexical()
    except Exception as e:
        logger.warning(f"[embed_doc_file] lexical rebuild 실패: {e}")

    registry[key] = {"sha": sha, "abs": str(p), "staged": str(staged),
                     "pages": len(img_pages)}
    _save_registry(reg_path, registry)

    return {"status": "done", "chunks": len(img_pages), "pages": len(img_pages)}


# ── MR (Movie/Music) stubs ─────────────────────────────────────────────
# Movie/Rec 파이프라인은 MR_TriCHEF/ 로 분리되어 독립 실행.
# [P3.1] 과거: no-op 스텁이 `IncrementalResult(0,0,0)` 을 반환하여 /reindex
# 응답이 "성공 + files=0" 으로 보여 호출자가 **무반응을 성공으로 오인**하는 문제.
# 이제: NotImplementedError 로 명시적 실패 → /reindex 엔드포인트가 error 필드로
# 포워딩하여 호출자가 MR_TriCHEF CLI 를 쓰도록 유도.
_MR_GUIDANCE = (
    "MR_TriCHEF 로 분리됨. CLI 사용: "
    "`python MR_TriCHEF/scripts/run_{movie,music}_incremental.py` "
    "또는 `python -m MR_TriCHEF.pipeline.{movie,music}_runner`. "
    "/reindex?scope=all 은 image/document 만 처리함."
)


def run_movie_incremental() -> IncrementalResult:
    logger.warning("[run_movie_incremental] " + _MR_GUIDANCE)
    raise NotImplementedError("movie: " + _MR_GUIDANCE)


def run_music_incremental() -> IncrementalResult:
    logger.warning("[run_music_incremental] " + _MR_GUIDANCE)
    raise NotImplementedError("music: " + _MR_GUIDANCE)
