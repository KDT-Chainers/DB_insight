"""보컬 스템에서 MFCC·스펙트럼·크로마 등 보컬 전용 특징 벡터 추출."""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np

warnings.filterwarnings("ignore", category=UserWarning, module="librosa")


def _zero_vec(dim: int) -> np.ndarray:
    return np.zeros(dim, dtype=np.float64)


def compute_vocal_feature_vector(
    y_v: np.ndarray,
    sr: int,
) -> tuple[dict[str, Any], np.ndarray]:
    """
    보컬 스템 파형 → (flat dict, 46d 벡터).
    RMS가 너무 낮으면 (무음 스템) 영벡터 반환.
    """
    import librosa

    rms = float(np.sqrt(np.mean(y_v ** 2)))
    if rms < 1e-7 or y_v.size < 512:
        flat = {
            "vocal_rms_mean": 0.0,
            "vocal_spectral_centroid_mean": 0.0,
            "vocal_spectral_centroid_std": 0.0,
            "vocal_zcr_mean": 0.0,
            "vocal_hf_energy_ratio": 0.0,
            "vocal_brightness": 0.0,
        }
        return flat, _zero_vec(46)

    cent = librosa.feature.spectral_centroid(y=y_v, sr=sr)
    zcr = librosa.feature.zero_crossing_rate(y_v)
    rolloff = librosa.feature.spectral_rolloff(y=y_v, sr=sr)
    mfcc = librosa.feature.mfcc(y=y_v, sr=sr, n_mfcc=13)
    chroma = librosa.feature.chroma_stft(y=y_v, sr=sr)

    S = np.abs(librosa.stft(y_v, n_fft=2048))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    e_low = float(np.mean(S[freqs < 2000.0, :]))
    e_hi = float(np.mean(S[freqs >= 4000.0, :]))
    hf_ratio = e_hi / (e_low + 1e-9)

    flat = {
        "vocal_rms_mean": float(np.mean(librosa.feature.rms(y=y_v))),
        "vocal_rms_std": float(np.std(librosa.feature.rms(y=y_v))),
        "vocal_spectral_centroid_mean": float(np.mean(cent)),
        "vocal_spectral_centroid_std": float(np.std(cent)),
        "vocal_rolloff_mean": float(np.mean(rolloff)),
        "vocal_zcr_mean": float(np.mean(zcr)),
        "vocal_hf_energy_ratio": float(hf_ratio),
        "vocal_brightness": float(np.mean(cent)) / 4000.0,
    }

    parts: list[np.ndarray] = [
        np.array(
            [
                flat["vocal_rms_mean"] * 15.0,
                flat["vocal_rms_std"] * 15.0,
                flat["vocal_spectral_centroid_mean"] / 8000.0,
                flat["vocal_spectral_centroid_std"] / 4000.0,
                flat["vocal_rolloff_mean"] / 20000.0,
                flat["vocal_zcr_mean"],
                np.log1p(flat["vocal_hf_energy_ratio"]) / 3.0,
                flat["vocal_brightness"],
            ],
            dtype=np.float64,
        ),
        np.mean(mfcc, axis=1).astype(np.float64) / 100.0,
        np.std(mfcc, axis=1).astype(np.float64) / 100.0,
        np.mean(chroma, axis=1).astype(np.float64),
    ]
    vec = np.concatenate(parts, dtype=np.float64)
    return flat, vec
