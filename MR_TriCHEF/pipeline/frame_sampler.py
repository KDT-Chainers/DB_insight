"""적응형 프레임 샘플링 + 오디오 추출 (ffmpeg)."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

FFMPEG  = "ffmpeg"
FFPROBE = "ffprobe"

# NVDEC(GPU 디코드) 사용 여부 캐시.
# True/False/None(unknown). 첫 호출 시 한번만 prove → 이후 재사용.
# RTX 4070 Laptop + ffmpeg cuvid 빌드 환경에서 영상 프레임 추출 5~10x 가속.
# 환경변수 OMC_DISABLE_NVDEC=1 로 강제 OFF.
_HWACCEL_OK: bool | None = None


def _hwaccel_available() -> bool:
    """`ffmpeg -hwaccels` 출력에 'cuda' 가 있는지 1회 검사하고 캐시."""
    global _HWACCEL_OK
    if _HWACCEL_OK is not None:
        return _HWACCEL_OK
    if os.environ.get("OMC_DISABLE_NVDEC", "").strip() in ("1", "true", "yes"):
        _HWACCEL_OK = False
        return False
    try:
        out = subprocess.check_output(
            [FFMPEG, "-hide_banner", "-hwaccels"],
            stderr=subprocess.STDOUT, text=True, timeout=5,
        )
        _HWACCEL_OK = bool(re.search(r"^\s*cuda\s*$", out, re.M))
    except Exception:
        _HWACCEL_OK = False
    logger.info(f"[frame_sampler] NVDEC available: {_HWACCEL_OK}")
    return _HWACCEL_OK


@dataclass
class SampledFrame:
    path:     Path
    t_start:  float   # 대표 시각(초)
    t_end:    float


def probe_duration(video: Path) -> float:
    """ffprobe 로 재생 시간(초) 추출."""
    try:
        out = subprocess.check_output(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            stderr=subprocess.STDOUT, text=True,
        )
        return float(out.strip())
    except Exception:
        return 0.0


def extract_frames(video: Path, out_dir: Path,
                   fps: float = 0.5,
                   scene_thresh: float = 0.2) -> list[SampledFrame]:
    """적응형 프레임 추출.

    • 기본 fps=0.5 → 2초당 1장
    • scene_thresh > 0 이면 scene change 시점도 추가 (OR 조건)
    반환: 프레임 경로 + 대표 시각(초).
    """
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    interval = 1.0 / fps  # 초
    # select: scene change  OR  evenly-spaced sample (interval-based)
    # `not(mod(t, X))` 는 부동소수점 PTS와 정확히 일치해야 트루 → 일부
    # 비정수 fps 영상에서 0 프레임 출력 → MJPEG 인코더 초기화 실패 (rc=-22).
    # `gte(t-prev_selected_t, X) + isnan(prev_selected_t)` 는 첫 프레임을
    # 무조건 선택하고 이후 X초 간격으로 선택하므로 모든 영상에서 견고함.
    expr = (f"gt(scene,{scene_thresh})"
            f"+gte(t-prev_selected_t\\,{interval:.4f})"
            f"+isnan(prev_selected_t)")
    pattern = out_dir / "f_%05d.jpg"

    base_args = [
        "-vf", f"select='{expr}',showinfo,scale='min(640,iw)':-2",
        "-vsync", "vfr", "-q:v", "3",
        str(pattern),
    ]

    def _run_ffmpeg(cmd: list[str]) -> subprocess.CompletedProcess:
        """ffmpeg 실행 — stderr를 항상 캡처해 진단 가능하도록."""
        return subprocess.run(cmd, stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE,
                              text=True, errors="replace")

    # NVDEC 가속 시도 → 실패 시 software 폴백.
    # `-hwaccel cuda` 만 사용 (output_format 미지정) — 필터 체인이 CPU 프레임 요구.
    proc = None
    use_hw = _hwaccel_available()
    if use_hw:
        cmd_hw = [
            FFMPEG, "-hide_banner", "-loglevel", "info",
            "-hwaccel", "cuda",
            "-i", str(video),
            *base_args,
        ]
        proc = _run_ffmpeg(cmd_hw)
        if proc.returncode != 0:
            logger.warning(f"[frame_sampler] NVDEC 실패, SW 폴백: {video.name} "
                           f"(rc={proc.returncode})")
            proc = None

    if proc is None:
        # software path (NVDEC 미지원 또는 폴백)
        cmd_sw = [
            FFMPEG, "-hide_banner", "-loglevel", "info",
            "-i", str(video),
            *base_args,
        ]
        proc = _run_ffmpeg(cmd_sw)

    frames = sorted(out_dir.glob("f_*.jpg"))

    # 0 프레임 폴백: select 필터가 0 프레임을 출력해 MJPEG 인코더가
    # 초기화 실패한 경우, 단순 fps 필터로 재시도.
    if proc.returncode != 0 or not frames:
        logger.warning(
            f"[frame_sampler] primary extract failed/empty: {video.name} "
            f"(rc={proc.returncode}, frames={len(frames)}). "
            f"fps-only 폴백으로 재시도."
        )
        # stderr 마지막 일부를 디버그 로그로 (full은 대용량 가능)
        if proc.stderr:
            logger.debug(f"[frame_sampler] stderr_tail: {proc.stderr[-400:]}")
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd_fb = [
            FFMPEG, "-hide_banner", "-loglevel", "warning",
            "-i", str(video),
            "-vf", f"fps={fps},scale='min(640,iw)':-2",
            "-q:v", "3", str(pattern),
        ]
        fb_proc = _run_ffmpeg(cmd_fb)
        frames = sorted(out_dir.glob("f_*.jpg"))
        if fb_proc.returncode != 0 or not frames:
            # 진짜 실패 — 원본 stderr와 함께 raise
            raise subprocess.CalledProcessError(
                fb_proc.returncode if fb_proc.returncode != 0 else proc.returncode,
                cmd_fb if fb_proc.returncode != 0 else (cmd_hw if use_hw else cmd_sw),
                output=None,
                stderr=(fb_proc.stderr or proc.stderr or "")[-1000:],
            )
        # 폴백 성공: showinfo 없이 pts_time 추출 불가 → 균등 분배 사용
        proc = fb_proc

    # showinfo 출력: "pts_time:12.345" 형태로 추출 (선택된 프레임 순서대로)
    pts_times = [float(m) for m in re.findall(r"pts_time:([\d.]+)", proc.stderr or "")]
    dur = probe_duration(video)
    interval_fallback = 1.0 / fps

    sampled: list[SampledFrame] = []
    for i, fp in enumerate(frames):
        if i < len(pts_times):
            t0 = round(pts_times[i], 3)
            # t_end: 다음 프레임 시각 또는 duration 까지
            t1 = round(pts_times[i + 1], 3) if i + 1 < len(pts_times) else round(min(dur, t0 + interval_fallback), 3)
        else:
            # pts_time 파싱 실패 시 fallback: 균등 분배
            n = max(1, len(frames))
            step = dur / n if dur > 0 else interval_fallback
            t0 = round(i * step, 3)
            t1 = round(min(dur, t0 + step), 3)
        sampled.append(SampledFrame(path=fp, t_start=t0, t_end=t1))
    return sampled


def extract_audio(video_or_audio: Path, out_wav: Path,
                  sample_rate: int = 16000) -> Path:
    """Whisper 입력용 16kHz mono WAV 추출."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_or_audio),
        "-ac", "1", "-ar", str(sample_rate),
        "-f", "wav", str(out_wav),
    ]
    subprocess.run(cmd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_wav
