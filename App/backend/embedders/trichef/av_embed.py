"""embedders/trichef/av_embed.py — 앱 UI → MR_TriCHEF 단일파일 어댑터.

동영상/음성 파일 1개를 MR_TriCHEF TRI-CHEF 파이프라인으로 임베딩.
MR_TriCHEF/pipeline 의 모델·캐시 유틸을 재사용하며,
incremental_runner.py 의 image/doc 어댑터와 동일한 반환 포맷 사용.

반환 dict:
  {"status": "done",    ...}
  {"status": "skipped", "reason": str}
  {"status": "error",   "reason": str}
"""
from __future__ import annotations

import gc
import os
import shutil
import sys
import tempfile
import time
import logging
from pathlib import Path
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

# ── Windows symlink 권한 오류 방지 (WinError 1314) ──────────────────────────
# HuggingFace Hub 가 캐시 디렉토리에 snapshot symlink 를 생성할 때
# Windows Developer Mode / 관리자 권한이 없으면 OSError(WinError 1314)가 발생.
# os.symlink 를 monkey-patch 하여 실패 시 파일 복사로 대체한다.
# (lazy import 함수 안에서 faster-whisper / hf_hub 가 임포트되기 전에 적용되어야 함)
_orig_symlink = os.symlink

def _safe_symlink(src, dst, target_is_directory=False, *, dir_fd=None):
    try:
        _orig_symlink(src, dst, target_is_directory=target_is_directory)
    except OSError:
        _abs = (src if os.path.isabs(src)
                else os.path.normpath(os.path.join(os.path.dirname(dst), src)))
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(_abs, dst)
        except Exception as _e:
            logger.debug(f"[symlink fallback] copy failed: {_e}")

os.symlink = _safe_symlink
# ────────────────────────────────────────────────────────────────────────────

# ── MR_TriCHEF 패키지 경로 등록 ────────────────────────────────────────
# av_embed.py: App/backend/embedders/trichef/av_embed.py
# parents[4]:  DB_insight/
_MR_ROOT = Path(__file__).resolve().parents[4] / "MR_TriCHEF"
if not _MR_ROOT.is_dir():
    raise ImportError(
        f"MR_TriCHEF 디렉토리를 찾을 수 없습니다: {_MR_ROOT}\n"
        "동영상·음성 인덱싱을 사용하려면 MR_TriCHEF/ 가 DB_insight/ 아래에 있어야 합니다."
    )
if str(_MR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MR_ROOT))

# MR_TriCHEF 공통 유틸 (경량 — 모델 로드 없음)
from pipeline.paths import MOVIE_CACHE_DIR, MOVIE_EXTS, MUSIC_CACHE_DIR, MUSIC_EXTS
from pipeline import cache as mr_cache, registry as mr_registry
from pipeline.frame_sampler import extract_audio, extract_frames, probe_duration


# ══════════════════════════════════════════════════════════════════════
# STT 정렬 헬퍼 (movie_runner.py 에서 복사 — 패키지 간 순환 import 방지)
# ══════════════════════════════════════════════════════════════════════

def _align_stt_to_frames(
    stt_segs: list[dict],
    frame_times: list[tuple[float, float]],
) -> list[str]:
    """각 프레임 구간(t_start, t_end) 과 겹치는 STT 텍스트를 concat."""
    out: list[str] = []
    for (f0, f1) in frame_times:
        chunks = [s["text"] for s in stt_segs if s["end"] >= f0 and s["start"] <= f1]
        out.append(" ".join(chunks).strip())
    return out


def _build_mixed_text(stt_t: str, orig_t: str) -> str:
    parts = [p.strip() for p in [stt_t, orig_t] if p.strip()]
    return "\n".join(parts) if parts else " "


def _sliding_windows(
    stt_segs: list[dict],
    duration: float,
    original_transcript: str = "",
    win: float = 30.0,
    hop: float = 15.0,
) -> list[dict]:
    """30초 윈도우, 15초 hop — music_runner.py 와 동일 로직."""
    windows: list[dict] = []
    t = 0.0
    idx = 0
    while t < max(duration, win):
        w0, w1 = t, t + win
        chunks = [s["text"] for s in stt_segs if s["end"] >= w0 and s["start"] <= w1]
        stt_text = " ".join(chunks).strip()
        windows.append({
            "window_idx":          idx,
            "t_start":             round(w0, 2),
            "t_end":               round(min(w1, duration if duration > 0 else w1), 2),
            "stt_transcript":      stt_text,
            "original_transcript": original_transcript,
            "text":                _build_mixed_text(stt_text, original_transcript),
        })
        t += hop
        idx += 1
        if duration > 0 and t >= duration:
            break
    if not windows:
        fallback = _build_mixed_text("", original_transcript)
        windows = [{"window_idx": 0, "t_start": 0.0, "t_end": round(duration, 2),
                    "stt_transcript": "", "original_transcript": original_transcript,
                    "text": fallback}]
    return windows


# ══════════════════════════════════════════════════════════════════════
# 동영상 — TRI-CHEF Re/Im/Z
# ══════════════════════════════════════════════════════════════════════

MOVIE_STEPS = [
    (1, 5, "프레임 추출 중..."),
    (2, 5, "SigLIP2 Re + DINOv2 Z 임베딩 중..."),
    (3, 5, "Whisper STT 변환 중..."),
    (4, 5, "BGE-M3 Im 임베딩 중..."),
    (5, 5, "벡터 캐시 저장 중..."),
]


def embed_movie_file(file_path: str, progress_cb: Callable | None = None) -> dict:
    """동영상 파일 1개 → MR_TriCHEF TRI-CHEF 임베딩 (Re/Im/Z).

    Args:
        file_path:   원본 동영상 절대경로
        progress_cb: (step, total, detail) → bool  (True 반환 시 중단)

    반환:
        {"status": "done",    "frames": int, "segs": int}
        {"status": "skipped", "reason": str}
        {"status": "error",   "reason": str}
    """
    from pipeline.vision import SigLIP2Encoder, DINOv2Encoder
    from pipeline.text import BGEM3Encoder
    from pipeline.stt import WhisperSTT

    def _cb(step_idx: int) -> bool:
        if progress_cb:
            s, t, d = MOVIE_STEPS[step_idx]
            return bool(progress_cb(step=s, total=t, detail=d))
        return False

    src = Path(file_path)
    if not src.is_file():
        return {"status": "skipped", "reason": "파일이 없음"}
    if src.suffix.lower() not in MOVIE_EXTS:
        return {"status": "skipped", "reason": f"지원하지 않는 확장자: {src.suffix}"}

    # registry 키: 절대경로(포워드 슬래시) — 앱 UI 오픈에 사용
    rel = str(src).replace("\\", "/")
    reg_path = MOVIE_CACHE_DIR / "registry.json"
    reg = mr_registry.load(reg_path)

    sha = mr_registry.sha256(src)
    if reg.get(rel, {}).get("sha") == sha:
        return {"status": "skipped", "reason": "이미 인덱싱됨 (SHA 일치)"}

    t0 = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="app_movie_"))
    try:
        # ── Step 1: 프레임 + 오디오 추출 ──────────────────────────
        if _cb(0):
            return {"status": "skipped", "reason": "사용자 중단"}
        frames = extract_frames(src, tmp / "frames", fps=0.5, scene_thresh=0.2)
        if not frames:
            return {"status": "error", "reason": "ffmpeg 프레임 추출 실패 (ffmpeg 설치 필요)"}
        wav = extract_audio(src, tmp / "audio.wav")
        dur = probe_duration(src)
        frame_paths = [f.path for f in frames]
        logger.info(f"[movie] {src.name}: {len(frames)} frames, dur={dur:.1f}s")

        # ── Step 2: SigLIP2 Re (1152d) + DINOv2 Z (1024d) ─────────
        if _cb(1):
            return {"status": "skipped", "reason": "사용자 중단"}
        sig = SigLIP2Encoder()
        Re = sig.embed_images(frame_paths, batch=8)
        sig.unload(); del sig; gc.collect()

        dino = DINOv2Encoder()
        Z = dino.embed_images(frame_paths, batch=8)
        dino.unload(); del dino; gc.collect()

        # ── Step 3: Whisper STT ────────────────────────────────────
        if _cb(2):
            return {"status": "skipped", "reason": "사용자 중단"}
        stt_m = WhisperSTT()
        stt_segs = stt_m.transcribe(wav, language=None)
        stt_m.unload(); del stt_m; gc.collect()
        logger.info(f"[movie] {src.name}: {len(stt_segs)} STT segments")

        # ── Step 4: BGE-M3 Im (1024d) ─────────────────────────────
        if _cb(3):
            return {"status": "skipped", "reason": "사용자 중단"}
        frame_times = [(f.t_start, f.t_end) for f in frames]
        frame_stt = _align_stt_to_frames(stt_segs, frame_times)

        bge = BGEM3Encoder()
        Im = bge.embed([t if t else " " for t in frame_stt], batch=16)
        bge.unload(); del bge; gc.collect()

        # ── Step 5: 캐시 저장 ─────────────────────────────────────
        if _cb(4):
            return {"status": "skipped", "reason": "사용자 중단"}
        ids = [rel] * len(frames)
        seg_meta = [
            {
                "file":        rel,
                "file_path":   str(src),    # 절대경로 — UI 파일 열기에 사용
                "file_name":   src.name,
                "frame_idx":   i,
                "t_start":     f.t_start,
                "t_end":       f.t_end,
                "stt_text":    frame_stt[i],
            }
            for i, f in enumerate(frames)
        ]
        mr_cache.replace_by_file(
            cache_dir=MOVIE_CACHE_DIR,
            file_keys=[rel],
            arrays={"Re": Re, "Im": Im, "Z": Z},
            new_ids=ids,
            new_segs=seg_meta,
            npy_prefix="cache_movie",
            ids_file="movie_ids.json",
            segs_file="segments.json",
        )
        reg[rel] = {"sha": sha, "frames": len(frames), "duration": dur}
        mr_registry.save(reg_path, reg)

        # ── ASF 자산 재빌드 (segments.json → vocab_movie.json + movie_token_sets.json) ──
        # unified_engine.search_av() 의 ASF 채널이 활성화되려면 이 파일이 필요.
        try:
            from pipeline.build_asf_assets import build_for as _build_asf
            _build_asf(MOVIE_CACHE_DIR, "movie")
            logger.info(f"[movie] ASF 자산 재빌드 완료")
        except Exception as _asf_e:
            logger.warning(f"[movie] ASF 재빌드 실패 (검색에 ASF 채널 비활성): {_asf_e}")

        elapsed = round(time.time() - t0, 1)
        logger.info(f"[movie] {src.name}: done in {elapsed}s")
        return {"status": "done", "frames": len(frames), "segs": len(stt_segs)}

    except Exception as e:
        import traceback
        logger.error(f"[movie] {src.name}: {traceback.format_exc()}")
        return {"status": "error", "reason": f"{type(e).__name__}: {e}"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════
# 음성/음악 — TRI-CHEF Re/Im/Z (Z = zeros)
# ══════════════════════════════════════════════════════════════════════

MUSIC_STEPS = [
    (1, 4, "오디오 표준화 중..."),
    (2, 4, "Whisper STT 변환 중..."),
    (3, 4, "BGE-M3 Im + SigLIP2 Re 임베딩 중..."),
    (4, 4, "벡터 캐시 저장 중..."),
]


def embed_music_file(file_path: str, progress_cb: Callable | None = None) -> dict:
    """음성/음악 파일 1개 → MR_TriCHEF TRI-CHEF 임베딩 (Re/Im/Z=0).

    Args:
        file_path:   원본 음성 절대경로
        progress_cb: (step, total, detail) → bool  (True 반환 시 중단)

    반환:
        {"status": "done",    "windows": int}
        {"status": "skipped", "reason": str}
        {"status": "error",   "reason": str}
    """
    from pipeline.vision import SigLIP2Encoder
    from pipeline.text import BGEM3Encoder
    from pipeline.stt import WhisperSTT

    def _cb(step_idx: int) -> bool:
        if progress_cb:
            s, t, d = MUSIC_STEPS[step_idx]
            return bool(progress_cb(step=s, total=t, detail=d))
        return False

    src = Path(file_path)
    if not src.is_file():
        return {"status": "skipped", "reason": "파일이 없음"}
    if src.suffix.lower() not in MUSIC_EXTS:
        return {"status": "skipped", "reason": f"지원하지 않는 확장자: {src.suffix}"}

    rel = str(src).replace("\\", "/")
    reg_path = MUSIC_CACHE_DIR / "registry.json"
    reg = mr_registry.load(reg_path)

    sha = mr_registry.sha256(src)
    if reg.get(rel, {}).get("sha") == sha:
        return {"status": "skipped", "reason": "이미 인덱싱됨 (SHA 일치)"}

    t0 = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="app_music_"))
    try:
        # ── Step 1: 오디오 표준화 (16kHz mono WAV) ─────────────────
        if _cb(0):
            return {"status": "skipped", "reason": "사용자 중단"}
        wav = extract_audio(src, tmp / "audio.wav")
        dur = probe_duration(src)

        # ── Step 2: Whisper STT ────────────────────────────────────
        if _cb(1):
            return {"status": "skipped", "reason": "사용자 중단"}
        stt_m = WhisperSTT()
        stt_segs = stt_m.transcribe(wav, language=None)
        stt_m.unload(); del stt_m; gc.collect()

        stt_status = "ok" if any(s["text"].strip() for s in stt_segs) else "no_speech"
        # original_transcript: 파일명을 원본 전사 대리값으로 사용
        original_transcript = src.stem.replace("_", " ").replace("-", " ")
        windows = _sliding_windows(stt_segs, duration=dur,
                                   original_transcript=original_transcript)
        win_texts = [w["text"] for w in windows]
        logger.info(f"[music] {src.name}: {len(stt_segs)} STT segs, "
                    f"{len(windows)} windows, stt_status={stt_status}")

        # ── Step 3: BGE-M3 Im (1024d) + SigLIP2 Re (1152d) ────────
        if _cb(2):
            return {"status": "skipped", "reason": "사용자 중단"}
        bge = BGEM3Encoder()
        Im = bge.embed(win_texts, batch=64)
        bge.unload(); del bge; gc.collect()

        sig = SigLIP2Encoder()
        Re = sig.embed_texts(win_texts)
        sig.unload(); del sig; gc.collect()

        Z = np.zeros((Im.shape[0], 1024), dtype=np.float32)

        # ── Step 4: 캐시 저장 ─────────────────────────────────────
        if _cb(3):
            return {"status": "skipped", "reason": "사용자 중단"}
        ids = [rel] * len(windows)
        seg_meta = [
            {
                "file":                rel,
                "file_path":           str(src),    # 절대경로
                "file_name":           src.name,
                "window_idx":          w["window_idx"],
                "t_start":             w["t_start"],
                "t_end":               w["t_end"],
                "stt_text":            w["stt_transcript"],
                "original_transcript": w["original_transcript"],
                "text":                w["text"],
                "stt_status":          stt_status,
            }
            for w in windows
        ]
        mr_cache.replace_by_file(
            cache_dir=MUSIC_CACHE_DIR,
            file_keys=[rel],
            arrays={"Re": Re, "Im": Im, "Z": Z},
            new_ids=ids,
            new_segs=seg_meta,
            npy_prefix="cache_music",
            ids_file="music_ids.json",
            segs_file="segments.json",
        )
        reg[rel] = {"sha": sha, "windows": len(windows),
                    "duration": dur, "stt_status": stt_status}
        mr_registry.save(reg_path, reg)

        # ── ASF 자산 재빌드 (segments.json → vocab_music.json + music_token_sets.json) ──
        try:
            from pipeline.build_asf_assets import build_for as _build_asf
            _build_asf(MUSIC_CACHE_DIR, "music")
            logger.info(f"[music] ASF 자산 재빌드 완료")
        except Exception as _asf_e:
            logger.warning(f"[music] ASF 재빌드 실패 (검색에 ASF 채널 비활성): {_asf_e}")

        elapsed = round(time.time() - t0, 1)
        logger.info(f"[music] {src.name}: done in {elapsed}s")
        return {"status": "done", "windows": len(windows)}

    except Exception as e:
        import traceback
        logger.error(f"[music] {src.name}: {traceback.format_exc()}")
        return {"status": "error", "reason": f"{type(e).__name__}: {e}"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
