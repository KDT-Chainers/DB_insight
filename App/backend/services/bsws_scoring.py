"""BSWS — Bragg-Scherrer Weighted Score.

XRD 5-phase 분석의 단일 파장 측정 + Bragg peak intensity + Scherrer coherent
length 비유. Occam's razor 원칙으로 가장 단순한 통합 ranking 공식.

수학적 형식:
    BSWS(r, d, q) = z(r, d) × coh(d) × aff(d, q)

여기서:
    z(r, d):   peak position within domain
                = clip((dense_r - mean_d) / (top1_d - mean_d), 0, 1)
                도메인 내 두드러짐 (강매칭=1, 평균=0)

    coh(d):    Domain coherence (Bragg + Scherrer hybrid)
                = 0.5 × (top1_d - mean_d) / top1_d           (Scherrer style)
                + 0.5 × max(0, top1_d - 0.5) / 0.5           (raw intensity)
                도메인 자체의 결정성 — audio cluster 자동 페널티

    aff(d, q): Query-domain affinity (phase fraction)
                = 1.0 + 0.5 × count(query keywords in domain)
                "BGM" 키워드 → bgm 가중

핵심 효과 — Audio Cluster 자동 해결:
    audio top1=0.99, mean=0.95 → coh = 0.5×0.04 + 0.5×0.98 = 0.51
    video top1=0.95, mean=0.50 → coh = 0.5×0.47 + 0.5×0.90 = 0.685
    image top1=0.85, mean=0.65 → coh = 0.5×0.24 + 0.5×0.70 = 0.47

    audio 모든 결과 비슷한 cosine (cluster) → coh의 Scherrer 항이 작음.

Hyperparameters: 3개 (coh blend, raw threshold, aff boost) — Occam's razor.
"""
from __future__ import annotations
import math
from typing import Iterable

# 도메인 의도 키워드 (cmp_scoring.py 와 동일)
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "bgm":   ["bgm", "배경음악", "ost", "효과음", "사운드트랙", "광고음악"],
    "audio": ["음악", "노래", "보컬", "팟캐스트", "녹음", "오디오", "음성"],
    "image": ["이미지", "사진", "그림", "그래픽", "캡션", "픽쳐", "image", "photo"],
    "video": ["동영상", "영상", "다큐", "방송", "뉴스", "비디오", "movie", "video"],
    "doc":   ["문서", "pdf", "보고서", "논문", "도서", "단행본", "보도자료"],
}

# Hyperparameters (Occam's razor — 3개)
COH_BLEND   = 0.5    # Scherrer + raw intensity blend
RAW_THRESH  = 0.5    # raw intensity 하한 (이하 0)
AFF_BOOST   = 0.5    # query keyword 매칭당 boost


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _raw_cosine(r: dict) -> float:
    """결과 dict 에서 raw cosine 추출.

    AV 도메인은 cosine_top1 (search_av metadata) 우선,
    없으면 dense (raw cosine 평균).
    """
    ft = r.get("file_type", "")
    if ft in ("video", "audio"):
        v = r.get("cosine_top1") or r.get("dense") or 0
    else:
        v = r.get("dense") or 0
    return float(v)


def domain_coherence(domain_pool: Iterable[float]) -> float:
    """Bragg + Scherrer hybrid coherence ∈ [0, 1].

    audio cluster (top1≈mean) 자동 페널티: Scherrer 항이 0 에 가까움.
    하지만 raw intensity 가 높으면 일부 보상.

    Returns:
        0 (도메인 자체 무관) ~ 1 (강매칭 cluster 명확).
    """
    arr = [float(x) for x in domain_pool]
    if not arr:
        return 0.0
    top1 = max(arr)
    mean = sum(arr) / len(arr)
    # Scherrer-style: peak sharpness
    scherrer = (top1 - mean) / max(top1, 1e-6)
    # Raw intensity contribution: top1 이 RAW_THRESH 이상이면 보너스
    raw_bonus = max(0.0, top1 - RAW_THRESH) / max(1.0 - RAW_THRESH, 1e-6)
    return _clip01(COH_BLEND * scherrer + (1 - COH_BLEND) * raw_bonus)


def peak_position(raw: float, domain_pool: Iterable[float]) -> float:
    """도메인 내 raw 의 peak position ∈ [0, 1] (top1=1, mean=0)."""
    arr = [float(x) for x in domain_pool]
    if not arr:
        return 0.0
    top1 = max(arr)
    mean = sum(arr) / len(arr)
    span = max(top1 - mean, 1e-6)
    return _clip01((float(raw) - mean) / span)


def query_affinity(query: str, domain: str) -> float:
    """Query-domain affinity (phase fraction)."""
    if not query or not domain:
        return 1.0
    q_lower = query.lower()
    kws = DOMAIN_KEYWORDS.get(domain, [])
    hits = sum(1 for kw in kws if kw.lower() in q_lower)
    return min(2.0, 1.0 + AFF_BOOST * hits)


def compute_bsws(r: dict, domain_pool: Iterable[float],
                 query: str, domain: str) -> float:
    """BSWS — 도메인 무관 [0,1] 통합 score.

    BSWS(r, d, q) = z(r, d) × coh(d) × aff(d, q)
    """
    I = _raw_cosine(r)
    z = peak_position(I, domain_pool)
    coh = domain_coherence(domain_pool)
    aff = query_affinity(query, domain)
    return _clip01(z * coh * aff)


def apply_bsws_to_results(results_by_domain: dict[str, list[dict]],
                           query: str,
                           set_confidence: bool = True) -> dict:
    """5도메인 결과에 BSWS 일괄 적용 (in-place).

    각 결과에 'bsws_score', 'domain_coh', 'peak_z' 추가 +
    set_confidence=True 면 'confidence' 갱신.
    """
    # 도메인별 raw cosine pool 미리 계산 (재사용)
    domain_pools: dict[str, list[float]] = {}
    domain_coh: dict[str, float] = {}
    for dom, lst in results_by_domain.items():
        pool = [_raw_cosine(r) for r in lst]
        domain_pools[dom] = pool
        domain_coh[dom] = domain_coherence(pool)

    for dom, lst in results_by_domain.items():
        pool = domain_pools[dom]
        coh = domain_coh[dom]
        aff = query_affinity(query, dom)
        for r in lst:
            I = _raw_cosine(r)
            z = peak_position(I, pool)
            score = _clip01(z * coh * aff)
            r["bsws_score"]  = round(score, 4)
            r["domain_coh"]  = round(coh, 4)
            r["peak_z"]      = round(z, 4)
            r["domain_aff"]  = round(aff, 2)
            if set_confidence:
                if "similarity" not in r or r.get("similarity") is None:
                    r["similarity"] = round(I, 4)
                r["confidence"] = round(score, 4)
    return results_by_domain
