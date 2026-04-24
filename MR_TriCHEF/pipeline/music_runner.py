"""Music 파이프라인 — 파일별 End-to-End 증분 처리.

SHA 체크 → 오디오 표준화 → Whisper STT → 30초 sliding window 텍스트 concat
       → BGE-M3(Im=1024d) + SigLIP2-text(Re=1152d) + zeros(Z=1024d) → 캐시 append → 레지스트리 저장

축 설계:
  Re = SigLIP2 text-encoder (1152d) — Movie Re(이미지) 와 동일 공간 → 크로스-도메인 검색 호환
  Im = BGE-M3 (1024d)               — STT 텍스트 언어 유사도
  Z  = zeros  (1024d)               — 음악은 시각 구조 없음

[항목1] STT 3필드 분리 (PROJECT_PIPELINE_SPEC §5):
  stt_transcript      : Whisper 인식 결과
  original_transcript : 원본 가사/파일명 메타 (현재 파일명 stem 사용, 향후 ID3 태그로 확장)
  text (mixed)        : 검색용 — stt_transcript + original_transcript 혼합

[항목2] mixed 텍스트 모드:
  BGM처럼 STT가 없는 파일은 original_transcript(파일명)만으로 Im 임베딩 생성 → 검색 품질 유지

[항목7] stt_status 명시:
  "ok"       : Whisper 인식 성공 (텍스트 1개 이상)
  "no_speech": BGM/무음 등 텍스트 없음 — 실패 숨김 없이 registry에 명시
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
from .frame_sampler import extract_audio, probe_duration
from .paths import MUSIC_CACHE_DIR, MUSIC_EXTS, MUSIC_RAW_DIR
from .stt import WhisperSTT
from .text import BGEM3Encoder
from .vision import SigLIP2Encoder


Z_DIM_MUSIC  = 1024   # Movie DINOv2-large 와 동일 차원, 값은 0 벡터
RE_DIM_MUSIC = 1152   # SigLIP2 text-encoder — Movie Re(이미지 1152d)와 동일 공간


@dataclass
class FileResult:
    rel_path: str
    status:   str
    windows:  int = 0
    duration: float = 0.0
    elapsed:  float = 0.0
    reason:   str = ""


def _build_mixed_text(stt_t: str, orig_t: str) -> str:
    """[항목2] STT + original_transcript 혼합 검색 텍스트 생성.

    - 양쪽 모두 있으면: "stt_text\\noriginal_text"
    - STT만 있으면: stt_text
    - original만 있으면 (BGM 무음): original_text
    - 둘 다 없으면: " " (BGE-M3 빈 입력 방지)
    """
    parts = [p.strip() for p in [stt_t, orig_t] if p.strip()]
    return "\n".join(parts) if parts else " "


def _sliding_windows(stt_segs: list[dict], duration: float,
                     original_transcript: str = "",
                     win: float = 30.0, hop: float = 15.0) -> list[dict]:
    """30초 윈도우, 15초 hop. 각 윈도우에 겹치는 STT text concat.

    [항목1] 3필드 구조:
      stt_transcript      : Whisper 인식 결과
      original_transcript : 파일 공통 원본 전사 (파일명 stem 등)
      text                : mixed 검색 텍스트 (항목2)
    """
    windows: list[dict] = []
    t = 0.0
    idx = 0
    while t < max(duration, win):
        w0, w1 = t, t + win
        chunks: list[str] = []
        for s in stt_segs:
            if s["end"] < w0 or s["start"] > w1:
                continue
            chunks.append(s["text"])
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
    fallback_text = _build_mixed_text("", original_transcript)
    return windows or [{"window_idx": 0, "t_start": 0.0,
                        "t_end": round(duration, 2),
                        "stt_transcript": "", "original_transcript": original_transcript,
                        "text": fallback_text}]


def iter_music_files() -> list[Path]:
    if not MUSIC_RAW_DIR.exists():
        return []
    return sorted(
        p for p in MUSIC_RAW_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in MUSIC_EXTS
    )


def run_music_incremental(
    progress: Callable[[str], None] | None = None,
) -> Iterator[FileResult]:
    def log(msg: str):
        if progress:
            progress(msg)

    reg_path = MUSIC_CACHE_DIR / "registry.json"
    reg      = registry.load(reg_path)

    files = iter_music_files()
    log(f"[music] 대상 {len(files)}개 (소스: {MUSIC_RAW_DIR})")
    if not files:
        return

    for idx, aud in enumerate(files, 1):
        t0 = time.time()
        rel = str(aud.relative_to(MUSIC_RAW_DIR)).replace("\\", "/")
        log(f"\n[music {idx}/{len(files)}] {rel}")

        sha = registry.sha256(aud)
        if reg.get(rel, {}).get("sha") == sha:
            log("  ⏩ 이미 인덱싱됨 — skip")
            yield FileResult(rel_path=rel, status="skipped", reason="sha match")
            continue

        tmp = Path(tempfile.mkdtemp(prefix="mmtri_music_"))
        try:
            log("  · ffmpeg 오디오 표준화 (16kHz mono)")
            wav = extract_audio(aud, tmp / "audio.wav")
            dur = probe_duration(aud)

            log("  · Whisper STT 로드 → transcribe")
            stt = WhisperSTT()
            stt_segs = stt.transcribe(wav, language=None)
            # [항목7] stt_status 명시 — 빈 transcript를 성공으로 숨기지 않음
            stt_status = "ok" if any(s["text"].strip() for s in stt_segs) else "no_speech"
            log(f"    → {len(stt_segs)} segments (stt_status={stt_status})")
            stt.unload(); del stt; gc.collect()

            # [항목2] original_transcript: 파일명 stem을 원본 전사 대리값으로 사용.
            # 향후 ID3/VorbisComment 태그에서 가사·아티스트·제목을 추출하면 교체.
            original_transcript = aud.stem.replace("_", " ").replace("-", " ")

            windows = _sliding_windows(stt_segs, duration=dur,
                                       original_transcript=original_transcript)
            log(f"  · 30s 윈도우 {len(windows)}개 구성 (mixed 텍스트)")

            # [항목1+2] mixed text 사용 — STT 없는 BGM도 파일명으로 Im 임베딩 생성
            win_texts = [w["text"] for w in windows]

            log("  · BGE-M3 로드 → Im 임베딩 (STT 언어 의미, 1024d)")
            bge = BGEM3Encoder()
            Im = bge.embed(win_texts, batch=16)    # (N, 1024)
            bge.unload(); del bge; gc.collect()

            log("  · SigLIP2 text-encoder 로드 → Re 임베딩 (1152d, Movie 와 동일 공간)")
            sig = SigLIP2Encoder()
            Re = sig.embed_texts(win_texts)        # (N, 1152)
            sig.unload(); del sig; gc.collect()

            Z  = np.zeros((Im.shape[0], Z_DIM_MUSIC), dtype=np.float32)

            cache.append_npy(MUSIC_CACHE_DIR / "cache_music_Re.npy", Re)
            cache.append_npy(MUSIC_CACHE_DIR / "cache_music_Im.npy", Im)
            cache.append_npy(MUSIC_CACHE_DIR / "cache_music_Z.npy",  Z)

            ids = [rel] * len(windows)
            cache.append_ids(MUSIC_CACHE_DIR / "music_ids.json", ids)

            seg_meta = [
                {
                    "file":                rel,
                    "file_name":           aud.name,
                    "window_idx":          w["window_idx"],
                    "t_start":             w["t_start"],
                    "t_end":               w["t_end"],
                    # [항목1] 3필드 분리
                    "stt_text":            w["stt_transcript"],
                    "original_transcript": w["original_transcript"],
                    "text":                w["text"],          # mixed (검색용)
                    # [항목7] stt_status — no_speech 명시
                    "stt_status":          stt_status,
                }
                for w in windows
            ]
            cache.append_segments(MUSIC_CACHE_DIR / "segments.json", seg_meta)

            # [항목7] registry에 stt_status 기록
            reg[rel] = {"sha": sha, "windows": len(windows), "duration": dur,
                        "stt_status": stt_status}
            registry.save(reg_path, reg)

            el = round(time.time() - t0, 1)
            log(f"  ✅ done — windows={len(windows)} duration={dur:.1f}s elapsed={el}s")
            yield FileResult(
                rel_path=rel, status="done",
                windows=len(windows), duration=dur, elapsed=el,
            )

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            log(f"  ❌ 오류: {e}\n{tb[:800]}")
            yield FileResult(rel_path=rel, status="error", reason=str(e)[:300])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
