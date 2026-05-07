"""
오디오 특징 수치 → 자연어 태그 문자열.
TF-IDF / 문장 임베딩 입력용 의사-문서 텍스트 생성.
"""
from __future__ import annotations

from typing import Any


def features_to_tags(flat: dict[str, Any]) -> str:
    """
    librosa 특징 dict → 자연어 태그 문자열 반환.
    영·한 혼합으로 ko-sroberta 임베딩에 최적화.
    """
    tempo = float(flat.get("tempo_bpm", 120))
    sc = float(flat.get("spectral_centroid_mean", 2000))
    zcr = float(flat.get("zcr_mean", 0.05))
    hp = float(flat.get("harm_perc_ratio", 1.0))

    # 템포 / 속도감
    if tempo < 95:
        pace = "slow tempo calm 느린 잔잔한 조용한"
    elif tempo < 125:
        pace = "moderate tempo mid 중간 템포"
    else:
        pace = "fast tempo upbeat 빠른 활기찬 신나는"

    # 음색 밝기
    if sc < 1800:
        tone = "dark warm low spectral 어두운 낮은 저음"
    elif sc < 3500:
        tone = "balanced neutral 중성 균형"
    else:
        tone = "bright airy high spectral 밝은 화사한 고음"

    # 노이즈 / 타격감
    if zcr > 0.12:
        nois = "noisy percussive 타격감 드럼"
    else:
        nois = "smooth harmonic 부드러운 하모닉"

    # 선율 vs 리듬
    if hp > 2.0:
        harm = "harmonic melodic 선율 위주 멜로디"
    elif hp < 0.8:
        harm = "rhythmic percussive 리듬 위주 비트"
    else:
        harm = "mixed harmonic percussive 혼합 밸런스"

    # 음량 / 에너지
    rms = float(flat.get("rms_mean", 0.05))
    if rms < 0.03:
        dyn = "quiet soft 조용 작은 볼륨"
    elif rms < 0.1:
        dyn = "medium loudness 중간 볼륨"
    else:
        dyn = "loud energetic 강한 에너지 큰 볼륨"

    parts = [pace, tone, nois, harm, dyn, "music audio track 음악"]

    # 보컬 특징 (유효한 경우)
    if flat.get("vocal_rms_mean") and float(flat.get("vocal_rms_mean", 0)) > 1e-6:
        vc = float(flat.get("vocal_spectral_centroid_mean", 2000))
        vhf = float(flat.get("vocal_hf_energy_ratio", 0))
        if vc < 2000:
            vp = "vocal warm chesty 따뜻한 보컬 낮은 목소리"
        elif vc < 3800:
            vp = "vocal balanced natural 중성 보컬 자연스러운"
        else:
            vp = "vocal bright airy 밝은 고음 보컬"
        if vhf > 0.35:
            vp += " breathy airy 쉰 목소리 공기감"
        parts.append(vp)
    else:
        parts.append("instrumental 반주 보컬 없음")

    return " ".join(parts)
