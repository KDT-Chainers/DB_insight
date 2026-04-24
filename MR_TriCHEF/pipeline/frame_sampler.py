"""적응형 프레임 샘플링 + 오디오 추출 (ffmpeg)."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

FFMPEG  = "ffmpeg"
FFPROBE = "ffprobe"


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
    # select: scene change  OR  uniform interval
    expr = f"gt(scene,{scene_thresh})+not(mod(t,{interval:.4f}))"
    pattern = out_dir / "f_%05d.jpg"

    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "info",
        "-i", str(video),
        "-vf", f"select='{expr}',showinfo,scale='min(640,iw)':-2",
        "-vsync", "vfr", "-q:v", "3",
        str(pattern),
    ]
    # loglevel=info 로 showinfo 의 pts_time 을 stderr 에서 캡처.
    proc = subprocess.run(cmd, check=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                          errors="replace")

    # showinfo 출력: "pts_time:12.345" 형태로 추출 (선택된 프레임 순서대로)
    pts_times = [float(m) for m in re.findall(r"pts_time:([\d.]+)", proc.stderr)]

    frames = sorted(out_dir.glob("f_*.jpg"))
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
