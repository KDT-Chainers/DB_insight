"""
보컬 스템 추정.
기본: HPSS 하모닉 + 보컬 대역 대역통과 (경량, 별도 설치 불필요).
선택: 환경 변수 MUSIC_SEARCH_USE_DEMUCS=1 + demucs 설치 시 htdemucs 사용.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np


def _bandpass_sos(y: np.ndarray, sr: int, fmin: float, fmax: float) -> np.ndarray:
    from scipy import signal

    nyq = sr / 2.0
    low = max(fmin / nyq, 1e-5)
    high = min(fmax / nyq, 0.99)
    if low >= high:
        return y
    sos = signal.butter(4, [low, high], btype="band", output="sos")
    return signal.sosfiltfilt(sos, y)


def separate_vocals_hpss_bandpass(
    y: np.ndarray,
    sr: int,
    fmin: float = 180.0,
    fmax: float = 7800.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """HPSS 하모닉 성분 + 대역통과 필터로 보컬 근사."""
    import librosa

    y_h, y_p = librosa.effects.hpss(y)
    y_bp = _bandpass_sos(y_h, sr, fmin, fmax)
    peak_in = float(np.max(np.abs(y)) + 1e-9)
    peak_v = float(np.max(np.abs(y_bp)) + 1e-9)
    y_v = y_bp * (peak_in / peak_v)
    info: dict[str, Any] = {
        "method": "hpss_harmonic_bandpass",
        "fmin_hz": fmin,
        "fmax_hz": fmax,
        "harm_rms": float(np.sqrt(np.mean(y_h ** 2))),
        "perc_rms": float(np.sqrt(np.mean(y_p ** 2))),
        "vocal_rms": float(np.sqrt(np.mean(y_v ** 2))),
    }
    return y_v.astype(np.float32), info


def _separate_vocals_demucs(
    audio_path: Path,
    cache_dir: Path,
) -> tuple[np.ndarray | None, dict[str, Any]]:
    """Demucs htdemucs로 vocals.wav 생성 후 로드. 실패 시 None 반환."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_sub = cache_dir / "demucs_out"
    out_sub.mkdir(parents=True, exist_ok=True)
    demucs_exe = os.environ.get("DEMUCS_PYTHON", "").strip() or None
    cmd = [
        demucs_exe or sys.executable,
        "-m", "demucs.separate",
        "-n", "htdemucs",
        "--two-stems", "vocals",
        "-o", str(out_sub),
        str(audio_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=3600)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        return None, {"method": "demucs", "error": str(e)}

    wavs = list(out_sub.rglob("vocals.wav"))
    if not wavs:
        return None, {"method": "demucs", "error": "vocals.wav not found"}

    try:
        import soundfile as sf
        v, sr = sf.read(str(wavs[0]), always_2d=False)
        if v.ndim > 1:
            v = np.mean(v, axis=1)
        if sr != 22050:
            import librosa
            v = librosa.resample(v.astype(np.float32), orig_sr=sr, target_sr=22050)
        return v.astype(np.float32), {"method": "demucs", "vocals_path": str(wavs[0])}
    except Exception as e:
        return None, {"method": "demucs", "error": str(e)}


def separate_vocals(
    y: np.ndarray,
    sr: int,
    audio_path: str | Path,
    *,
    max_seconds: float,
    cache_dir: Path | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    보컬에 가까운 파형 + 분리 메타 반환.
    MUSIC_SEARCH_USE_DEMUCS=1 환경 변수 설정 시 Demucs 사용.
    """
    use_demucs = os.environ.get("MUSIC_SEARCH_USE_DEMUCS", "").strip() in ("1", "true", "yes")
    path = Path(audio_path)
    if use_demucs and path.is_file() and cache_dir is not None:
        v_dem, info = _separate_vocals_demucs(path, cache_dir)
        if v_dem is not None and v_dem.size > 0:
            max_len = int(max_seconds * sr)
            if v_dem.shape[0] > max_len:
                v_dem = v_dem[:max_len]
            return v_dem, info

    return separate_vocals_hpss_bandpass(y, sr)
