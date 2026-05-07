"""mp4/mp3/wav → 16kHz/48kHz mono wav 추출. ffmpeg subprocess 호출.

ffmpeg가 PATH에 없으면 imageio_ffmpeg 백업 사용.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _ffmpeg_exe() -> str:
    """ffmpeg 실행파일 경로. PATH 우선, 없으면 imageio_ffmpeg fallback."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise RuntimeError(
            "ffmpeg를 찾을 수 없습니다. PATH 등록 또는 `pip install imageio-ffmpeg`."
        ) from e


def extract_wav(
    src: str | Path,
    dst: str | Path,
    *,
    sample_rate: int = 48000,
    duration: float | None = None,
    overwrite: bool = False,
) -> Path:
    """src(mp4/mp3/...) → dst(wav, mono, sample_rate).

    Args:
        src: 원본 미디어
        dst: 출력 wav
        sample_rate: 출력 샘플레이트 (CLAP=48000, librosa=22050)
        duration: 추출 길이 상한 (초). None이면 전체.
        overwrite: True면 기존 dst 덮어씀
    """
    src = Path(src)
    dst = Path(dst)
    if not src.is_file():
        raise FileNotFoundError(f"입력 파일 없음: {src}")

    if dst.exists() and not overwrite:
        return dst

    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg_exe(),
        "-y",
        "-i", str(src),
        "-vn",                     # video 제거
        "-ac", "1",                # mono
        "-ar", str(sample_rate),
        "-acodec", "pcm_s16le",
    ]
    if duration is not None and duration > 0:
        cmd += ["-t", str(duration)]
    cmd.append(str(dst))

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
    except subprocess.CalledProcessError as e:
        msg = e.stderr.decode("utf-8", errors="replace")[-500:] if e.stderr else ""
        raise RuntimeError(f"ffmpeg 변환 실패 ({src.name}): {msg}") from e
    return dst


def load_wav(path: str | Path, *, sr: int = 48000, max_seconds: float | None = None):
    """wav/mp3/mp4 → numpy float32 mono. librosa 의존."""
    import librosa
    import numpy as np
    y, _sr = librosa.load(str(path), sr=sr, mono=True, duration=max_seconds)
    if y.size == 0:
        raise ValueError(f"빈 오디오: {path}")
    return y.astype(np.float32), int(_sr)
