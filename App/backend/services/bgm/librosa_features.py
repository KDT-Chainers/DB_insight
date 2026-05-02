"""librosa 기반 룰베이스 음악 특징 — BPM, MFCC, chroma, HPSS 비율, RMS.

music_search_20260422/audio_features.py 의 mix 부분을 포팅 (보컬 분리는 제외).
산출물:
  flat: dict — UI 표시용 단순 숫자
  vec : np.ndarray — 클러스터링/태깅 입력
  tags: list[str] — "calm" / "fast" / "vocal-heavy" 등 룰베이스 라벨
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np

warnings.filterwarnings("ignore", category=UserWarning, module="librosa")


def compute_features(y: np.ndarray, sr: int) -> tuple[dict[str, Any], np.ndarray]:
    """y(mono float32) → (flat dict, feature vector)."""
    import librosa

    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    tempo = float(np.atleast_1d(tempo)[0]) if np.size(tempo) else 120.0
    if not np.isfinite(tempo) or tempo <= 0:
        tempo = 120.0

    cent    = librosa.feature.spectral_centroid(y=y, sr=sr)
    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)
    zcr     = librosa.feature.zero_crossing_rate(y)
    mfcc    = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20)
    chroma  = librosa.feature.chroma_stft(y=y, sr=sr)

    y_h, y_p   = librosa.effects.hpss(y)
    harm_e     = float(np.mean(y_h ** 2))
    perc_e     = float(np.mean(y_p ** 2))
    hp_ratio   = harm_e / (perc_e + 1e-9)

    rms = librosa.feature.rms(y=y)[0]

    flat = {
        "tempo_bpm":              float(tempo),
        "spectral_centroid_mean": float(np.mean(cent)),
        "spectral_centroid_std":  float(np.std(cent)),
        "spectral_rolloff_mean":  float(np.mean(rolloff)),
        "zcr_mean":               float(np.mean(zcr)),
        "harm_perc_ratio":        float(hp_ratio),
        "rms_mean":               float(np.mean(rms)),
        "rms_std":                float(np.std(rms)),
        "duration_sec":           float(len(y) / sr),
    }

    vec = np.concatenate(
        [
            np.array(
                [
                    flat["tempo_bpm"] / 200.0,
                    flat["spectral_centroid_mean"] / 8000.0,
                    flat["spectral_centroid_std"] / 4000.0,
                    flat["spectral_rolloff_mean"] / 20000.0,
                    flat["zcr_mean"],
                    np.log1p(flat["harm_perc_ratio"]) / 5.0,
                    flat["rms_mean"] * 10.0,
                    flat["rms_std"] * 10.0,
                ],
                dtype=np.float64,
            ),
            np.mean(mfcc, axis=1).astype(np.float64) / 100.0,
            np.std(mfcc, axis=1).astype(np.float64) / 100.0,
            np.mean(chroma, axis=1).astype(np.float64),
        ],
        dtype=np.float64,
    )
    return flat, vec


def features_to_tags(flat: dict[str, Any]) -> list[str]:
    """flat 특징 → 룰베이스 라벨 리스트."""
    tags: list[str] = []
    bpm = flat.get("tempo_bpm", 120.0)
    if bpm < 75:
        tags.append("slow")
    elif bpm < 110:
        tags.append("medium-tempo")
    else:
        tags.append("fast")

    centroid = flat.get("spectral_centroid_mean", 0.0)
    if centroid < 1500:
        tags.append("dark-timbre")
    elif centroid < 3500:
        tags.append("warm-timbre")
    else:
        tags.append("bright-timbre")

    hp = flat.get("harm_perc_ratio", 1.0)
    if hp > 5:
        tags.append("melodic")
    elif hp < 0.5:
        tags.append("rhythmic")

    rms = flat.get("rms_mean", 0.0)
    if rms < 0.02:
        tags.append("quiet")
    elif rms > 0.15:
        tags.append("loud")

    zcr = flat.get("zcr_mean", 0.0)
    if zcr > 0.12:
        tags.append("noisy")

    duration = flat.get("duration_sec", 0.0)
    if duration < 30:
        tags.append("short-clip")
    elif duration > 240:
        tags.append("long-track")

    return tags
