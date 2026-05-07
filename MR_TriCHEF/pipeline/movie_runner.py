"""Movie 파이프라인 — 파일별 End-to-End 증분 처리.

파일 1개 = SHA 체크 → 프레임 추출 → 오디오 추출 → STT → SigLIP2 Re
         → DINOv2 Z → STT 텍스트 프레임 정렬 → BGE-M3 Im → 캐시 append → 레지스트리 저장
"""
from __future__ import annotations

import gc
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from . import cache, registry
from .frame_sampler import extract_audio, extract_frames, probe_duration
from .paths import MOVIE_CACHE_DIR, MOVIE_EXTS, MOVIE_RAW_DIR
from .stt import WhisperSTT
from .text import BGEM3Encoder
from .vision import DINOv2Encoder, SigLIP2Encoder


@dataclass
class FileResult:
    rel_path: str
    status:   str         # "done" | "skipped" | "error"
    frames:   int = 0
    segs:     int = 0
    duration: float = 0.0
    elapsed:  float = 0.0
    reason:   str = ""


def _align_stt_to_frames(stt_segs: list[dict], frame_times: list[tuple[float, float]]
                         ) -> list[str]:
    """각 프레임(t_start, t_end) 과 시간상 겹치는 STT 세그먼트 text 를 concat."""
    out: list[str] = []
    for (f0, f1) in frame_times:
        chunks: list[str] = []
        for s in stt_segs:
            if s["end"] < f0 or s["start"] > f1:
                continue
            chunks.append(s["text"])
        out.append(" ".join(chunks).strip())
    return out


def iter_movie_files() -> list[Path]:
    if not MOVIE_RAW_DIR.exists():
        return []
    return sorted(
        p for p in MOVIE_RAW_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in MOVIE_EXTS
    )


def run_movie_incremental(
    progress: Callable[[str], None] | None = None,
) -> Iterator[FileResult]:
    """파일별로 순차 처리, 각 파일 완료마다 FileResult yield.

    모델은 도메인 루프 내 1회 로드 (메모리 제약 시 stage-sequential).
    """
    def log(msg: str):
        if progress:
            progress(msg)

    reg_path  = MOVIE_CACHE_DIR / "registry.json"
    reg       = registry.load(reg_path)

    files = iter_movie_files()
    log(f"[movie] 대상 {len(files)}개 (소스: {MOVIE_RAW_DIR})")
    if not files:
        return

    # 모델 로드 (순차: VRAM 보호)
    log("[movie] 모델 준비 — Whisper → SigLIP2 → DINOv2 → BGE-M3 순차 로드")

    for idx, vid in enumerate(files, 1):
        t0 = time.time()
        rel = str(vid.relative_to(MOVIE_RAW_DIR)).replace("\\", "/")
        log(f"\n[movie {idx}/{len(files)}] {rel}")

        # 0) SHA 증분 체크
        sha = registry.sha256(vid)
        if reg.get(rel, {}).get("sha") == sha:
            log(f"  ⏩ 이미 인덱싱됨 — skip")
            yield FileResult(rel_path=rel, status="skipped", reason="sha match")
            continue

        tmp = Path(tempfile.mkdtemp(prefix="mmtri_movie_"))
        try:
            # 1) 프레임 + 오디오 추출
            log("  · ffmpeg 프레임 추출 (fps=0.5 + scene)")
            frames = extract_frames(vid, tmp / "frames", fps=0.5, scene_thresh=0.2)
            log(f"    → {len(frames)} frames")
            if not frames:
                yield FileResult(rel_path=rel, status="error", reason="no frames")
                continue

            log("  · ffmpeg 오디오 추출 (16kHz mono)")
            wav = extract_audio(vid, tmp / "audio.wav")
            dur = probe_duration(vid)

            frame_paths = [f.path for f in frames]

            # 2) SigLIP2 Re (1152d) — torch 모델 먼저
            log("  · SigLIP2 로드 → Re 임베딩")
            sig = SigLIP2Encoder()
            Re = sig.embed_images(frame_paths, batch=8)
            sig.unload(); del sig; gc.collect()

            # 3) DINOv2 Z (1024d)
            log("  · DINOv2 로드 → Z 임베딩")
            dino = DINOv2Encoder()
            Z = dino.embed_images(frame_paths, batch=8)
            dino.unload(); del dino; gc.collect()

            # 4) Whisper STT — CTranslate2 (별도 VRAM allocator) 는 뒤로
            log("  · Whisper STT 로드 (int8)")
            stt = WhisperSTT()
            log("    transcribing...")
            stt_segs = stt.transcribe(wav, language=None)
            log(f"    → {len(stt_segs)} segments")
            stt.unload()
            del stt; gc.collect()

            # 5) STT 프레임 정렬 → BGE-M3 Im (1024d) — torch, Whisper 뒤에 오직 하나
            frame_times = [(f.t_start, f.t_end) for f in frames]
            frame_stt_text = _align_stt_to_frames(stt_segs, frame_times)
            log("  · BGE-M3 로드 → Im 임베딩")
            bge = BGEM3Encoder()
            # 빈 텍스트는 공백으로 대체(모델이 0 벡터 유사한 값 반환)
            Im = bge.embed([t if t else " " for t in frame_stt_text], batch=16)
            bge.unload(); del bge; gc.collect()

            # 6) 캐시: replace-by-file (동일 파일 재인덱싱 시 stale 제거 후 교체)
            ids = [rel] * len(frames)
            seg_meta = [
                {
                    "file":        rel,
                    "file_path":   rel,   # replace_by_file 이 file_path 키 사용
                    "file_name":   vid.name,
                    "frame_idx":   i,
                    "t_start":     f.t_start,
                    "t_end":       f.t_end,
                    "stt_text":    frame_stt_text[i],
                }
                for i, f in enumerate(frames)
            ]
            res = cache.replace_by_file(
                cache_dir=MOVIE_CACHE_DIR,
                file_keys=[rel],
                arrays={"Re": Re, "Im": Im, "Z": Z},
                new_ids=ids,
                new_segs=seg_meta,
                npy_prefix="cache_movie",
                ids_file="movie_ids.json",
                segs_file="segments.json",
            )
            n_tot_Re = res["rows"]

            # 7) 레지스트리 체크포인트
            reg[rel] = {"sha": sha, "frames": len(frames), "duration": dur}
            registry.save(reg_path, reg)

            el = round(time.time() - t0, 1)
            log(f"  ✅ done — frames={len(frames)} Re_total={n_tot_Re} elapsed={el}s")
            yield FileResult(
                rel_path=rel, status="done",
                frames=len(frames), segs=len(stt_segs),
                duration=dur, elapsed=el,
            )

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            log(f"  ❌ 오류: {e}\n{tb[:800]}")
            yield FileResult(rel_path=rel, status="error", reason=str(e)[:300])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
