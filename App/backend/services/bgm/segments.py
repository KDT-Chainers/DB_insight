"""BGM 세그먼트 단위 인덱싱 — 동영상 내 timestamp 범위 검색 지원.

각 mp4 를 30초 윈도우(10초 hop, overlap 20초) 로 분할 → 각 세그먼트마다 CLAP 임베딩.
검색 결과: 파일 + (start, end) timestamp.

산출물:
  cache_seg_emb.npy        (M, 512) float32, L2-normalized — 모든 세그먼트 concat
  cache_seg_index.json     [{file_idx, filename, seg_idx, start, end}] — 행 i ↔ 세그먼트
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from . import audio_extract, bgm_config, clap_encoder, index_store

logger = logging.getLogger(__name__)


SEG_EMB_PATH    = bgm_config.INDEX_DIR / "cache_seg_emb.npy"
SEG_INDEX_PATH  = bgm_config.INDEX_DIR / "cache_seg_index.json"
SEG_FAISS_PATH  = bgm_config.INDEX_DIR / "cache_seg_faiss.faiss"

DEFAULT_WINDOW_SEC = 30.0
DEFAULT_HOP_SEC    = 10.0
MIN_SEG_SEC        = 5.0   # 5초 미만 세그먼트는 버림


def segment_ranges(
    duration_sec: float,
    *,
    window: float = DEFAULT_WINDOW_SEC,
    hop: float = DEFAULT_HOP_SEC,
    min_seg: float = MIN_SEG_SEC,
) -> list[tuple[float, float]]:
    """오디오 길이 → [(start, end)] 윈도우 리스트.

    duration_sec 가 window 보다 짧으면 1개 세그먼트로 반환.
    """
    if duration_sec < min_seg:
        return [(0.0, duration_sec)]
    if duration_sec <= window:
        return [(0.0, duration_sec)]
    out: list[tuple[float, float]] = []
    s = 0.0
    while s < duration_sec:
        e = min(s + window, duration_sec)
        if e - s >= min_seg:
            out.append((round(s, 2), round(e, 2)))
        if e >= duration_sec:
            break
        s += hop
    return out


def _segment_audio(y: np.ndarray, sr: int, ranges: list[tuple[float, float]]) -> list[np.ndarray]:
    """waveform y → 세그먼트 별 슬라이스 리스트."""
    out: list[np.ndarray] = []
    for s, e in ranges:
        i0 = int(s * sr)
        i1 = int(e * sr)
        if i1 > len(y):
            i1 = len(y)
        if i1 - i0 > 0:
            out.append(y[i0:i1])
        else:
            out.append(y)
    return out


def build_segment_index(
    *,
    window: float = DEFAULT_WINDOW_SEC,
    hop:    float = DEFAULT_HOP_SEC,
    progress_cb=None,
    skip_existing_seg: bool = True,
) -> dict[str, Any]:
    """meta JSON 의 모든 트랙 → 세그먼트 임베딩 구축.

    기존 audio cache (extracted_DB/Bgm/audio/*.wav) 를 재사용 — 추가 ffmpeg 호출 없음.

    Args:
        window: 세그먼트 길이 (초)
        hop:    세그먼트 간격 (초). hop < window 면 overlap.
        progress_cb: callable(stage, i, n, info)
        skip_existing_seg: 기존 cache_seg_emb.npy 가 있고 행 수 일치하면 스킵

    Returns:
        요약 dict
    """
    meta = index_store.MetaStore(bgm_config.META_PATH)
    items = meta.all()
    if not items:
        return {"ok": False, "error": "BGM meta 없음 — 먼저 build_index 실행"}

    # 사전 계산: 모든 세그먼트 (start, end) 쌍 생성
    all_ranges: list[tuple[int, int, str, float, float]] = []
    # (file_idx, seg_idx, filename, start, end)
    for fi, m in enumerate(items):
        dur = float(m.get("duration") or 0.0)
        if dur <= 0:
            # duration 추정 — wav 파일 길이로
            wav_path = bgm_config.AUDIO_CACHE_DIR / (Path(m.get("filename", "")).stem + ".wav")
            if wav_path.is_file():
                try:
                    import wave
                    with wave.open(str(wav_path), "rb") as wf:
                        dur = wf.getnframes() / wf.getframerate()
                except Exception:
                    dur = bgm_config.AUDIO_MAX_SECONDS
        ranges = segment_ranges(dur, window=window, hop=hop)
        for si, (s, e) in enumerate(ranges):
            all_ranges.append((fi, si, m.get("filename", ""), s, e))

    n_segments = len(all_ranges)
    logger.info(
        f"[bgm.segments] 트랙 {len(items)} → 세그먼트 {n_segments} "
        f"(window={window}s hop={hop}s)"
    )

    # 기존 임베딩 재사용 가능?
    existing_emb: np.ndarray | None = None
    existing_idx: list[dict] | None = None
    if skip_existing_seg and SEG_EMB_PATH.is_file() and SEG_INDEX_PATH.is_file():
        try:
            existing_emb = np.load(SEG_EMB_PATH)
            existing_idx = json.loads(SEG_INDEX_PATH.read_text(encoding="utf-8"))
            if (
                isinstance(existing_idx, list)
                and len(existing_idx) == existing_emb.shape[0] == n_segments
            ):
                # 동일 메타 → 그대로 사용
                logger.info(f"[bgm.segments] 기존 인덱스 재사용 ({n_segments} segs)")
                # FAISS 인덱스 재구축만
                idx = index_store.build_index(existing_emb)
                index_store.save_index(idx, SEG_FAISS_PATH)
                return {
                    "ok": True,
                    "n_files":    len(items),
                    "n_segments": n_segments,
                    "reused":     True,
                }
        except Exception as e:
            logger.warning(f"[bgm.segments] 기존 인덱스 로드 실패: {e}")

    # 세그먼트 임베딩 생성
    t0 = time.time()
    embeddings = np.zeros((n_segments, bgm_config.CLAP_DIM), dtype=np.float32)
    seg_meta: list[dict] = []
    n_done = 0
    n_fail = 0

    last_file_idx = -1
    cached_y = None
    cached_sr = None

    for ri, (fi, si, fname, s, e) in enumerate(all_ranges):
        if progress_cb:
            try:
                progress_cb("segment", ri + 1, n_segments, f"{fname} [{s:.0f}-{e:.0f}s]")
            except Exception:
                pass

        # 같은 파일 연속 처리 — wav 한 번만 로드
        if fi != last_file_idx:
            wav_path = bgm_config.AUDIO_CACHE_DIR / (Path(fname).stem + ".wav")
            if not wav_path.is_file():
                cached_y = None
            else:
                try:
                    cached_y, cached_sr = audio_extract.load_wav(
                        wav_path, sr=bgm_config.CLAP_SR,
                        max_seconds=None,
                    )
                except Exception as ex:
                    logger.warning(f"[bgm.segments] wav 로드 실패 {fname}: {ex}")
                    cached_y = None
            last_file_idx = fi

        if cached_y is None:
            seg_meta.append({
                "file_idx": fi, "seg_idx": si, "filename": fname,
                "start": s, "end": e,
            })
            n_fail += 1
            continue

        i0 = int(s * cached_sr)
        i1 = int(e * cached_sr)
        if i1 > len(cached_y):
            i1 = len(cached_y)
        seg_y = cached_y[i0:i1]
        if len(seg_y) < bgm_config.CLAP_SR:  # 1초 미만은 패딩
            pad = np.zeros(bgm_config.CLAP_SR - len(seg_y), dtype=np.float32)
            seg_y = np.concatenate([seg_y, pad])

        try:
            emb = clap_encoder.encode_audio([seg_y])[0]
            embeddings[ri] = emb
            n_done += 1
        except Exception as ex:
            logger.warning(f"[bgm.segments] CLAP 실패 {fname} [{s}-{e}]: {ex}")
            n_fail += 1

        seg_meta.append({
            "file_idx": fi, "seg_idx": si, "filename": fname,
            "start": s, "end": e,
        })

    # 저장
    np.save(SEG_EMB_PATH, embeddings)
    SEG_INDEX_PATH.write_text(
        json.dumps(seg_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    idx = index_store.build_index(embeddings)
    index_store.save_index(idx, SEG_FAISS_PATH)

    elapsed = time.time() - t0
    return {
        "ok":            True,
        "n_files":       len(items),
        "n_segments":    n_segments,
        "n_done":        n_done,
        "n_failed":      n_fail,
        "window":        window,
        "hop":           hop,
        "elapsed_sec":   round(elapsed, 1),
        "built_at":      datetime.now(timezone.utc).isoformat(),
    }


# ── 검색 헬퍼 ─────────────────────────────────────────────────────────────

def load_segment_index() -> tuple[Any, list[dict]] | None:
    """(faiss/numpy index, seg_meta list) 로드. 없으면 None."""
    if not SEG_INDEX_PATH.is_file():
        return None
    try:
        seg_meta = json.loads(SEG_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    idx = index_store.load_index(SEG_FAISS_PATH)
    if idx is None and SEG_EMB_PATH.is_file():
        idx = np.load(SEG_EMB_PATH)
    if idx is None:
        return None
    return idx, seg_meta


def search_segments(
    query_vec: np.ndarray,
    *,
    top_k: int = 30,
    per_file_limit: int = 3,
) -> list[dict] | None:
    """텍스트/오디오 query_vec → 세그먼트 검색 결과.

    각 파일당 best 세그먼트 ≤ per_file_limit 개씩 반환.
    Returns: [{filename, start, end, score, file_idx, seg_idx}, ...]
    """
    loaded = load_segment_index()
    if loaded is None:
        return None
    idx, seg_meta = loaded
    pool_k = min(top_k * 5, len(seg_meta))
    scores, seg_idxs = index_store.search(idx, query_vec, pool_k)

    by_file: dict[str, list[dict]] = {}
    for s, i in zip(scores.tolist(), seg_idxs.tolist()):
        if i < 0 or i >= len(seg_meta):
            continue
        m = seg_meta[i]
        fn = m.get("filename", "")
        rec = {
            "filename":  fn,
            "start":     float(m.get("start", 0.0)),
            "end":       float(m.get("end", 0.0)),
            "score":     float(s),
            "file_idx":  m.get("file_idx", -1),
            "seg_idx":   m.get("seg_idx", -1),
        }
        by_file.setdefault(fn, []).append(rec)

    flat: list[dict] = []
    for fn, segs in by_file.items():
        segs.sort(key=lambda r: -r["score"])
        flat.extend(segs[:per_file_limit])
    flat.sort(key=lambda r: -r["score"])
    return flat[:top_k]
