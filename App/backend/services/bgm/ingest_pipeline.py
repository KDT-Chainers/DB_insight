"""BGM 인덱스 빌드 파이프라인.

흐름 (102 mp4 → 인덱스):
  ① mp4 → wav 추출 (ffmpeg, extracted_DB/Bgm/audio/)
  ② Chromaprint 지문 (chromaprint_db.json)
  ③ CLAP 임베딩 (clap_emb.npy + clap_index.faiss)
  ④ librosa 특징 + tags (librosa_features.json)
  ⑤ filename parse + meta JSON (audio_meta.json)
  ⑥ (옵션) ACR catalog sync — bgm.api_enabled & auto_enrich_catalog 시

Resume:
  audio_meta.json 안에 이미 처리된 항목이 있으면 skip-existing.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from . import (
    acr_client,
    audio_extract,
    bgm_config,
    chromaprint as cp,
    clap_encoder,
    filename_parse,
    index_store,
    librosa_features,
)

logger = logging.getLogger(__name__)


SUPPORTED_EXTS = {".mp4", ".m4a", ".mp3", ".wav", ".flac", ".ogg", ".webm", ".mkv"}


def _list_sources(src_dir: Path) -> list[Path]:
    if not src_dir.is_dir():
        return []
    files = [
        p for p in sorted(src_dir.iterdir())
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    ]
    return files


def _wav_path(src: Path) -> Path:
    return bgm_config.AUDIO_CACHE_DIR / (src.stem + ".wav")


def build_index(
    *,
    src_dir: str | Path | None = None,
    rebuild: bool = False,
    sync_acr: bool = False,
    skip_existing: bool = True,
    progress_cb=None,
) -> dict[str, Any]:
    """전체 파이프라인 실행.

    Args:
        src_dir: 원본 mp4 폴더 (기본 raw_DB/Movie/정혜_BGM_1차)
        rebuild: True면 기존 캐시·인덱스 무시하고 전체 재빌드
        sync_acr: True 또는 (api_enabled & auto_enrich_catalog) 시 ACR 메타 보강
        skip_existing: 이미 처리된 트랙은 스킵
        progress_cb: callable(stage:str, i:int, n:int, info:str) — UI 진행 표시용

    Returns:
        요약 dict
    """
    src = Path(src_dir or bgm_config.RAW_BGM_DIR)
    files = _list_sources(src)
    if not files:
        return {
            "ok": False,
            "n_files": 0,
            "error": f"원본 디렉터리에 미디어 파일 없음: {src}",
        }

    # 기존 메타 로드 (resume)
    meta = index_store.MetaStore(bgm_config.META_PATH)
    if rebuild:
        meta.replace_all([])

    fp_db = cp.load_db(bgm_config.CHROMAPRINT_DB) if not rebuild else {}

    existing_keys = {it.get("filename") for it in meta.all()}
    todo: list[Path] = [p for p in files if (not skip_existing) or (p.name not in existing_keys)]

    summary = {
        "ok": True,
        "src_dir": str(src),
        "n_files":   len(files),
        "n_todo":    len(todo),
        "n_done":    0,
        "n_failed":  0,
        "stages":    {},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    if not todo:
        # 처리할 파일은 없지만 인덱스 재구축은 필요할 수 있음
        _rebuild_clap_index(meta)
        cp.save_db(bgm_config.CHROMAPRINT_DB, fp_db)
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        summary["note"] = "처리 대상 0건 — 기존 인덱스 재구축만 수행"
        return summary

    # CLAP 임베딩은 한꺼번에 모은 뒤 마지막에 인덱스 재구축
    new_items: list[dict[str, Any]] = list(meta.all())  # mutable working copy
    new_embeddings: list[np.ndarray] = []
    embedding_filenames: list[str] = []

    # 기존 임베딩 로드 (있으면)
    existing_emb: np.ndarray | None = None
    if (not rebuild) and bgm_config.CLAP_EMB_PATH.is_file():
        try:
            existing_emb = np.load(bgm_config.CLAP_EMB_PATH)
            if existing_emb.shape[0] != len(meta):
                logger.warning(
                    f"[bgm.ingest] 기존 emb 행수({existing_emb.shape[0]}) "
                    f"≠ meta({len(meta)}) — 임베딩만 재계산"
                )
                existing_emb = None
        except Exception as e:
            logger.warning(f"[bgm.ingest] 기존 emb 로드 실패: {e}")
            existing_emb = None

    t_start = time.time()

    for i, src_file in enumerate(todo, 1):
        if progress_cb:
            try:
                progress_cb("ingest", i, len(todo), src_file.name)
            except Exception:
                pass

        try:
            # ① mp4 → wav (CLAP용 48kHz)
            wav48 = _wav_path(src_file)
            audio_extract.extract_wav(
                src_file, wav48,
                sample_rate=bgm_config.CLAP_SR,
                duration=bgm_config.AUDIO_MAX_SECONDS,
                overwrite=False,
            )

            # ② Chromaprint
            fp_info = cp.fingerprint_file(src_file)
            if fp_info is not None:
                fp_db[src_file.name] = {
                    "fingerprint": fp_info[0],
                    "duration":    fp_info[1],
                }

            # ③ CLAP 임베딩
            try:
                emb = clap_encoder.encode_audio_file(
                    wav48, max_seconds=bgm_config.AUDIO_MAX_SECONDS,
                )
                new_embeddings.append(emb)
                embedding_filenames.append(src_file.name)
            except Exception as e:
                logger.warning(f"[bgm.ingest] CLAP 임베딩 실패 ({src_file.name}): {e}")

            # ④ librosa 특징
            try:
                y, sr = audio_extract.load_wav(
                    wav48, sr=22050,
                    max_seconds=bgm_config.AUDIO_MAX_SECONDS,
                )
                flat, _vec = librosa_features.compute_features(y, sr)
                tags = librosa_features.features_to_tags(flat)
            except Exception as e:
                logger.warning(f"[bgm.ingest] librosa 실패 ({src_file.name}): {e}")
                flat, tags = {}, []

            # ⑤ 메타
            ga, gt = filename_parse.guess_artist_title(src_file.name)
            item = {
                "filename":     src_file.name,
                # 절대경로 저장 (현 PC 기준). 다른 PC 에서는
                # routes/bgm.py serve_file 이 RAW_BGM_DIR/<filename> 으로 fallback,
                # 또는 scripts/normalize_registry_paths.py 로 일괄 정규화.
                "path":         str(src_file.resolve()),
                "guess_artist": ga,
                "guess_title":  gt,
                "duration":     float(fp_info[1]) if fp_info else flat.get("duration_sec", 0.0),
                "acr_artist":   "",
                "acr_title":    "",
                "acr_synced_at": None,
                "tags":         tags,
                "params":       flat,
            }

            existing_idx = next(
                (k for k, it in enumerate(new_items) if it.get("filename") == src_file.name),
                None,
            )
            if existing_idx is not None:
                # ACR 메타는 보존
                item["acr_artist"] = new_items[existing_idx].get("acr_artist", "")
                item["acr_title"]  = new_items[existing_idx].get("acr_title", "")
                item["acr_synced_at"] = new_items[existing_idx].get("acr_synced_at")
                new_items[existing_idx] = item
            else:
                new_items.append(item)

            summary["n_done"] += 1
        except Exception as e:
            logger.exception(f"[bgm.ingest] 파일 실패: {src_file.name}")
            summary["n_failed"] += 1
            continue

    # ── 메타 저장 ──────────────────────────────────────────────────────────
    meta.replace_all(new_items)

    # ── CLAP 임베딩 통합 + 인덱스 ──────────────────────────────────────────
    final_emb = _consolidate_embeddings(
        meta, existing_emb, new_embeddings, embedding_filenames,
    )
    np.save(bgm_config.CLAP_EMB_PATH, final_emb)
    idx = index_store.build_index(final_emb)
    index_store.save_index(idx, bgm_config.CLAP_INDEX_PATH)

    # ── Chromaprint DB 저장 ───────────────────────────────────────────────
    cp.save_db(bgm_config.CHROMAPRINT_DB, fp_db)

    # ── librosa features (디버그/대시보드용) ───────────────────────────────
    bgm_config.LIBROSA_FEATS.parent.mkdir(parents=True, exist_ok=True)
    bgm_config.LIBROSA_FEATS.write_text(
        json.dumps(
            [{"filename": it.get("filename"), "tags": it.get("tags", []), "params": it.get("params", {})}
             for it in new_items],
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    # ── (옵션) ACR sync ────────────────────────────────────────────────────
    auto_enrich = bool(bgm_config.get_bgm_setting("auto_enrich_catalog", True))
    if (sync_acr or auto_enrich) and bgm_config.is_api_enabled() and acr_client.is_configured():
        sync_n = sync_acr_metadata(only_missing=True, progress_cb=progress_cb)
        summary["stages"]["acr_sync"] = sync_n

    # ── 카탈로그 버전 ──────────────────────────────────────────────────────
    bgm_config.CATALOG_VERSION.write_text(
        json.dumps({
            "n_tracks":     len(new_items),
            "clap_dim":     int(final_emb.shape[1]) if final_emb.ndim == 2 else 0,
            "fp_db_size":   len(fp_db),
            "built_at":     datetime.now(timezone.utc).isoformat(),
            "elapsed_sec":  round(time.time() - t_start, 2),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    summary["elapsed_sec"] = round(time.time() - t_start, 2)
    return summary


def _consolidate_embeddings(
    meta: index_store.MetaStore,
    existing_emb: np.ndarray | None,
    new_embs: list[np.ndarray],
    new_filenames: list[str],
) -> np.ndarray:
    """meta 순서에 맞는 (N, D) 임베딩 행렬 생성.

    기존 임베딩 + 새로 계산한 임베딩 병합. 누락된 행은 0벡터로 채우되
    그런 행이 발생하면 경고.
    """
    items = meta.all()
    n = len(items)
    if n == 0:
        return np.zeros((0, bgm_config.CLAP_DIM), dtype=np.float32)

    new_map = {fn: emb for fn, emb in zip(new_filenames, new_embs)}
    dim = (
        new_embs[0].shape[0] if new_embs else
        (existing_emb.shape[1] if existing_emb is not None else bgm_config.CLAP_DIM)
    )
    out = np.zeros((n, dim), dtype=np.float32)
    missing = 0

    # 기존 임베딩 reuse 매핑 (filename → row idx in old)
    old_filenames: list[str] = []
    if existing_emb is not None:
        # 기존 meta 순서를 알 수 없으므로 캐시 무효화 시 0벡터.
        # 호출자가 rebuild=False && existing_emb.shape[0]==len(items) 보장한 상태.
        old_filenames = [it.get("filename", "") for it in items]

    for i, it in enumerate(items):
        fn = it.get("filename", "")
        if fn in new_map:
            out[i] = new_map[fn]
        elif (
            existing_emb is not None
            and i < existing_emb.shape[0]
            and i < len(old_filenames)
            and old_filenames[i] == fn
        ):
            out[i] = existing_emb[i]
        else:
            missing += 1

    if missing:
        logger.warning(f"[bgm.ingest] 임베딩 누락 행 {missing}개 — 검색 정확도 저하")
    return out


def sync_acr_metadata(*, only_missing: bool = True, progress_cb=None) -> int:
    """settings.bgm.api_enabled=True 일 때 102곡 ACR 메타 보강. 처리 건수 반환."""
    if not bgm_config.is_api_enabled():
        return 0
    if not acr_client.is_configured():
        return 0

    meta = index_store.MetaStore(bgm_config.META_PATH)
    items = meta.all()
    targets = []
    for it in items:
        if only_missing and (it.get("acr_title") or it.get("acr_artist")):
            continue
        targets.append(it)

    n_done = 0
    for i, it in enumerate(targets, 1):
        if progress_cb:
            try:
                progress_cb("acr_sync", i, len(targets), it.get("filename", ""))
            except Exception:
                pass

        # mp4가 아닌 추출된 wav를 보내는게 안정적
        wav = _wav_path(Path(it.get("path", "")))
        candidate = wav if wav.is_file() else Path(it.get("path", ""))
        if not candidate.is_file():
            continue
        result = acr_client.recognize(candidate)
        if result is None:
            continue
        meta.update_by_filename(it.get("filename", ""), {
            "acr_title":     result.get("title", ""),
            "acr_artist":    result.get("artist", ""),
            "acr_synced_at": datetime.now(timezone.utc).isoformat(),
        })
        n_done += 1
        time.sleep(0.5)  # ACR rate limit 보호

    return n_done
