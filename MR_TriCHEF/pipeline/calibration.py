"""도메인별 null 분포 calibration.

무관한 쿼리 코퍼스로 각 도메인 캐시의 스코어 분포 (μ, σ, p95) 측정.
검색 시 z-score 정규화하여 도메인 간 공정 비교.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .paths import MOVIE_CACHE_DIR, MUSIC_CACHE_DIR

# 의도적으로 저장 콘텐츠와 무관한 쿼리 (null 분포 추정용)
NULL_QUERIES = [
    "날씨가 맑다",
    "자동차 엔진 수리",
    "요리 레시피 김치찌개",
    "강아지 산책",
    "주식 시장 분석",
    "커피 원두 로스팅",
    "바다 서핑 파도",
    "컴퓨터 하드웨어 조립",
    "정원 가꾸기 식물",
    "비행기 공항 출국",
    "의사 병원 진료",
    "축구 경기 결과",
    "사진 촬영 카메라",
    "책 읽기 독서",
    "휴가 여행 계획",
    "화장품 메이크업",
    "게임 콘솔 플레이",
    "건강 운동 피트니스",
    "패션 옷 쇼핑",
    "영화 관람 후기",
]

CAL_PATH = Path(__file__).resolve().parent / "_calibration.json"


def measure_domain(cache_dir: Path, kind: str, encoders: dict) -> dict:
    """도메인 캐시 전체에 null 쿼리를 던져 스코어 분포 측정."""
    import json as _json

    Re_path = cache_dir / f"cache_{kind}_Re.npy"
    Im_path = cache_dir / f"cache_{kind}_Im.npy"
    if not Re_path.exists():
        return {"status": "no_cache"}

    Re = np.load(Re_path)
    Im = np.load(Im_path) if Im_path.exists() else None
    ids_path = cache_dir / f"{kind}_ids.json"
    ids = _json.loads(ids_path.read_text(encoding="utf-8")).get("ids", []) if ids_path.exists() else []

    bge = encoders["bge"]
    sig = encoders.get("sig")

    all_scores: list[float] = []

    for q in NULL_QUERIES:
        q_bge = bge.embed([q])[0]
        if kind == "movie" and sig is not None:
            q_sig = sig.embed_texts([q])[0]
            A = Re @ q_sig
            B = Im @ q_bge if Im is not None else np.zeros_like(A)
            per_seg = np.sqrt(A**2 + (0.4 * B)**2).astype(np.float32)
        else:  # music: A only
            per_seg = (Re @ q_bge).astype(np.float32)

        # 파일별 top-3 평균 집계 (search._aggregate 와 동일 구조)
        per_file: dict[str, list[float]] = {}
        for i, rel in enumerate(ids):
            per_file.setdefault(rel, []).append(float(per_seg[i]))
        for rel, scores in per_file.items():
            top = sorted(scores, reverse=True)[:3]
            all_scores.append(float(np.mean(top)))

    arr = np.array(all_scores, dtype=np.float32)
    return {
        "status":   "ok",
        "n":        int(arr.size),
        "mu_null":  float(arr.mean()),
        "sigma_null": float(arr.std() + 1e-6),
        "p95":      float(np.percentile(arr, 95)),
        "p99":      float(np.percentile(arr, 99)),
        "max":      float(arr.max()),
    }


def calibrate_crossmodal_movie(cache_dir: Path, encoders: dict,
                                sample_q: int = 30, pairs_per_q: int = 10) -> dict:
    """Movie 전용 crossmodal calibration.

    텍스트 쿼리 → 영상 프레임 벡터 경로로 null 분포 측정.
    (calibrate_null 은 frame↔frame = 이미지끼리 비교 → mu=0.85 과도 추정)
    여기서는 NULL_QUERIES 를 SigLIP2 text encoder 로 임베딩해
    실제 검색과 동일한 텍스트→이미지 cross-modal 분포를 측정한다.
    """
    Re_path = cache_dir / "cache_movie_Re.npy"
    Im_path = cache_dir / "cache_movie_Im.npy"
    if not Re_path.exists():
        return {"status": "no_cache"}

    Re = np.load(Re_path)   # (N, 1152) SigLIP2 이미지
    Im = np.load(Im_path)   # (N, 1024) BGE-M3 STT 텍스트

    bge = encoders["bge"]
    sig = encoders["sig"]

    rng = np.random.default_rng(42)
    queries = NULL_QUERIES[:sample_q]

    all_scores: list[float] = []
    for q in queries:
        q_Re = sig.embed_texts([q])[0]   # SigLIP2 text (1152d)
        q_Im = bge.embed([q])[0]          # BGE-M3 (1024d)
        N = Re.shape[0]
        j_idx = rng.integers(0, N, pairs_per_q)
        A = Re[j_idx] @ q_Re              # (pairs_per_q,)
        B = Im[j_idx] @ q_Im
        scores = np.sqrt(A**2 + (0.4 * B)**2)
        all_scores.extend(float(s) for s in scores)

    arr = np.array(all_scores, dtype=np.float32)
    mu  = float(arr.mean())
    sig_val = float(arr.std()) + 1e-6
    # FAR=0.05 → Φ⁻¹(0.95) ≈ 1.645
    thr = mu + 1.645 * sig_val

    return {
        "status":     "ok",
        "method":     "crossmodal_v1",
        "n":          int(arr.size),
        "mu_null":    mu,
        "sigma_null": sig_val,
        "p95":        float(np.percentile(arr, 95)),
        "p99":        float(np.percentile(arr, 99)),
        "abs_threshold": thr,
        "max":        float(arr.max()),
    }


def recalibrate() -> dict:
    """Movie + Music 모두 재측정 → json 저장.

    Movie: crossmodal_v1 (텍스트쿼리→프레임 분포)
    Music: 기존 null 분포 측정 (Re=Im=BGE-M3 이므로 동일 공간)
    """
    from .text import BGEM3Encoder
    from .vision import SigLIP2Encoder

    encoders = {"bge": BGEM3Encoder(), "sig": SigLIP2Encoder()}
    try:
        result = {
            "movie": calibrate_crossmodal_movie(MOVIE_CACHE_DIR, encoders),
            "music": measure_domain(MUSIC_CACHE_DIR, "music", encoders),
        }
    finally:
        encoders["bge"].unload()
        encoders["sig"].unload()

    CAL_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def load() -> dict:
    if CAL_PATH.exists():
        try:
            return json.loads(CAL_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def normalize(raw_score: float, domain: str, cal: dict | None = None) -> tuple[float, float]:
    """raw cos → (z_score, confidence).

    z = (raw - μ_null) / σ_null
    confidence = sigmoid(z / 2)   # z=0 → 0.5, z=2 → 0.88, z=4 → 0.98
    """
    import math
    cal = cal or load()
    d = cal.get(domain, {}) if cal else {}
    if d.get("status") != "ok":
        # fallback — 초기 상태: 원시 스코어 그대로, confidence는 sigmoid((raw-0.25)/0.08)
        return raw_score, 1.0 / (1.0 + math.exp(-(raw_score - 0.25) / 0.08))
    mu    = d["mu_null"]
    sigma = d["sigma_null"]
    z = (raw_score - mu) / sigma
    conf = 1.0 / (1.0 + math.exp(-z / 2.0))
    return z, conf
