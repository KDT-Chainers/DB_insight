"""
librosa 기반 오디오 특징 추출.
믹스 전체 특징 + 보컬 스템 특징 → 결합 벡터.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import numpy as np

from .feature_params import derive_track_params
from .vocal_features import compute_vocal_feature_vector
from .vocal_separation import separate_vocals

warnings.filterwarnings("ignore", category=UserWarning, module="librosa")

MAX_AUDIO_SECONDS = 90.0   # 인덱싱 시 앞에서 자를 길이(초)


def l2_normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n < 1e-12:
        return v
    return v / n


def _stats_to_vector(stats: dict[str, Any]) -> np.ndarray:
    parts: list[np.ndarray] = [
        np.array(
            [
                stats["tempo_bpm"] / 200.0,
                stats["spectral_centroid_mean"] / 8000.0,
                stats["spectral_centroid_std"] / 4000.0,
                stats["spectral_rolloff_mean"] / 20000.0,
                stats["zcr_mean"],
                np.log1p(stats["harm_perc_ratio"]) / 5.0,
                stats["rms_mean"] * 10.0,
                stats["rms_std"] * 10.0,
            ],
            dtype=np.float64,
        ),
        stats["mfcc_mean"].astype(np.float64).ravel() / 100.0,
        stats["mfcc_std"].astype(np.float64).ravel() / 100.0,
        stats["chroma_mean"].astype(np.float64).ravel(),
    ]
    return np.concatenate(parts, dtype=np.float64)


def compute_mix_features(y: np.ndarray, sr: int) -> tuple[dict[str, Any], np.ndarray]:
    """믹스 전체 파형 → (flat dict, 벡터)."""
    import librosa

    tempo, _beats = librosa.beat.beat_track(y=y, sr=sr)
    tempo = float(np.atleast_1d(tempo)[0]) if np.size(tempo) else 120.0
    if not np.isfinite(tempo) or tempo <= 0:
        tempo = 120.0

    cent = librosa.feature.spectral_centroid(y=y, sr=sr)
    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)
    zcr = librosa.feature.zero_crossing_rate(y)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20)
    chroma = librosa.feature.chroma_stft(y=y, sr=sr)

    y_h, y_p = librosa.effects.hpss(y)
    harm_energy = float(np.mean(y_h ** 2))
    perc_energy = float(np.mean(y_p ** 2))
    hp_ratio = harm_energy / (perc_energy + 1e-9)
    rms = librosa.feature.rms(y=y)[0]

    stats = {
        "tempo_bpm": tempo,
        "spectral_centroid_mean": float(np.mean(cent)),
        "spectral_centroid_std": float(np.std(cent)),
        "spectral_rolloff_mean": float(np.mean(rolloff)),
        "zcr_mean": float(np.mean(zcr)),
        "mfcc_mean": np.mean(mfcc, axis=1),
        "mfcc_std": np.std(mfcc, axis=1),
        "chroma_mean": np.mean(chroma, axis=1),
        "harm_perc_ratio": hp_ratio,
        "rms_mean": float(np.mean(rms)),
        "rms_std": float(np.std(rms)),
    }

    vec = _stats_to_vector(stats)
    flat = {
        "tempo_bpm": stats["tempo_bpm"],
        "spectral_centroid_mean": stats["spectral_centroid_mean"],
        "spectral_centroid_std": stats["spectral_centroid_std"],
        "spectral_rolloff_mean": stats["spectral_rolloff_mean"],
        "zcr_mean": stats["zcr_mean"],
        "harm_perc_ratio": stats["harm_perc_ratio"],
        "rms_mean": stats["rms_mean"],
        "rms_std": stats["rms_std"],
    }
    return flat, vec


def extract_all(
    audio_path: str,
    *,
    sr: int = 22050,
    max_seconds: float = MAX_AUDIO_SECONDS,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """
    오디오 파일 → 믹스 특징 + 보컬 스템 특징 + 결합 벡터 + 도출 파라미터.

    반환 키:
      flat_mix, flat_vocal, vec_mix, vec_vocal,
      vec_combined, separation, params
    """
    import librosa

    y, sr = librosa.load(audio_path, sr=sr, mono=True, duration=max_seconds)
    if y.size == 0:
        raise ValueError(f"빈 오디오: {audio_path}")

    flat_m, vec_m = compute_mix_features(y, sr)
    y_v, sep_info = separate_vocals(y, sr, audio_path, max_seconds=max_seconds, cache_dir=cache_dir)
    flat_v, vec_v = compute_vocal_feature_vector(y_v, sr)
    combined = np.concatenate([vec_m, vec_v], dtype=np.float64)
    params = derive_track_params(flat_m, flat_v, sep_info)

    return {
        "flat_mix": flat_m,
        "flat_vocal": flat_v,
        "vec_mix": vec_m,
        "vec_vocal": vec_v,
        "vec_combined": combined,
        "separation": sep_info,
        "params": params,
    }
