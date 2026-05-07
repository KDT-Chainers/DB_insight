"""
믹스·보컬 특징에서 분위기·보컬 파라미터 도출 (0~1 스케일).
"""
from __future__ import annotations

from typing import Any

import numpy as np


def _clip01(x: float) -> float:
    return float(max(0.0, min(1.0, x)))


def derive_track_params(
    flat_mix: dict[str, Any],
    flat_vocal: dict[str, Any],
    separation: dict[str, Any],
) -> dict[str, Any]:
    tempo = float(flat_mix.get("tempo_bpm", 120.0))
    sc = float(flat_mix.get("spectral_centroid_mean", 2000.0))
    rms_m = float(flat_mix.get("rms_mean", 0.05))
    hp = float(flat_mix.get("harm_perc_ratio", 1.0))

    vcent = float(flat_vocal.get("vocal_spectral_centroid_mean", 0.0))
    vrms = float(flat_vocal.get("vocal_rms_mean", 0.0))
    vhf = float(flat_vocal.get("vocal_hf_energy_ratio", 0.0))

    energy = _clip01(rms_m * 12.0)
    brightness = _clip01(sc / 6000.0)
    tempo_norm = _clip01((tempo - 60.0) / 120.0)
    harmonicity = _clip01(np.log1p(hp) / 3.0)

    vocal_brightness = _clip01(vcent / 6000.0) if vcent > 0 else 0.0
    vocal_presence = _clip01(vrms * 20.0)
    vocal_air = _clip01(np.log1p(vhf) / 4.0)

    mix_rms = float(flat_mix.get("rms_mean", 1e-6)) + 1e-9
    vocal_prominence = _clip01(vrms / mix_rms / 3.0)

    return {
        "separation_method": separation.get("method", "unknown"),
        "mood": {
            "energy": energy,
            "brightness": brightness,
            "tempo_norm": tempo_norm,
            "harmonic_emphasis": harmonicity,
        },
        "voice": {
            "vocal_brightness": vocal_brightness,
            "vocal_presence": vocal_presence,
            "vocal_air_hf": vocal_air,
            "vocal_prominence_vs_mix": vocal_prominence,
        },
    }
