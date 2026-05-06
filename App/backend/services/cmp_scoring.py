"""[v10.5] Calibrated Match Probability + Global Rank — 5도메인 통합 confidence.

목적:
  Doc / Image / Video / Audio / BGM 각각 다른 raw 매칭 점수 분포 (cosine, BM25,
  CLAP) 를 [0,1] 범위로 통일하여 도메인 간 비교 가능한 단일 metric 제공.

수학적 정의:
  쿼리 q, 결과 r, 도메인 d 에 대해
    raw(q, r, d)   : 도메인 원본 매칭 점수
    pool R_q       : 같은 쿼리의 모든 후보 raw_score
    z(r) = (raw - mean(R_q)) / std(R_q)              ← per-query 정규화
    CMP(r, d) = sigmoid(α_d · z(r) + β_d)            ← 도메인 calibration

  α_d, β_d 는 offline 학습 결과 (초기엔 default (1.0, 0.0)).

판별 임계값:
    CMP ≥ 0.95   압도적 매칭 (z ≥ 2.0)
    CMP ≥ 0.75   강한 매칭   (z ≥ 1.0)
    CMP ≥ 0.55   보통 매칭   (z ≥ 0.5)
    CMP ≥ 0.40   약한 매칭   (z ≥ 0.0)
    CMP <  0.40  무관 — '없음' 처리 권장
"""
from __future__ import annotations
import math
from typing import Iterable, Optional


# 도메인별 calibration (α, β). offline 학습 후 갱신.
# - α: z-score 민감도 (높을수록 가파른 sigmoid → 강매칭/약매칭 분리 강조)
# - β: bias (양수: 평균 conf 상승, 음수: 보수적)
#
# BGM CLAP 분포가 매우 좁으므로 conservative (낮은 α + 음수 β)
# Image SigLIP2 / Doc BGE-M3 는 일반적
DOMAIN_CALIBRATION: dict[str, tuple[float, float]] = {
    "doc":   (1.0, 0.0),
    "image": (1.0, 0.0),
    "video": (1.0, 0.0),
    "audio": (1.0, 0.0),
    "bgm":   (0.8, -0.2),
}

# 통합 임계값 — '없음' 판별
CMP_THRESHOLD_NONE = 0.40


# 도메인별 raw cosine floor — 'dense' 필드 (진짜 raw cosine) 분포 기반.
# similarity 는 video/audio 포화(=1.0), bgm cap(=0.75) 으로 도메인 비교 부적합.
# dense 는 search_av/_search_bgm 의 raw cosine pre-aggregation → 자연 분포.
#
# 측정 (top1 기준):
#   doc dense   ~0.87 (BGE-M3 raw cosine)
#   image dense ~0.82 (SigLIP2 raw cosine)
#   video dense ~0.95 (AV dense_agg)
#   audio dense ~0.99
#   bgm dense   ~0.64 (CLAP raw cosine, cap 없음)
#
# floor = 도메인 약매칭 자동 cut 임계값 (top1 보다 낮게 설정).
DOMAIN_RAW_FLOOR: dict[str, float] = {
    "doc":   0.55,
    "image": 0.50,
    "video": 0.62,
    "audio": 0.95,   # audio dense 0.98 cluster 특성 — 매우 높게 설정해도 거의 모두 통과
    "bgm":   0.40,
}


# 도메인 의도 키워드 — 쿼리에 포함 시 해당 도메인 가중 ↑
# 자연어 쿼리에서 사용자 의도 도메인 추출용 (예: "잔잔한 배경음악" → bgm/audio).
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "bgm":   ["bgm", "배경음악", "ost", "효과음", "사운드트랙", "광고음악"],
    "audio": ["음악", "노래", "보컬", "팟캐스트", "녹음", "오디오", "음성"],
    "image": ["이미지", "사진", "그림", "그래픽", "캡션", "픽쳐", "image", "photo"],
    "video": ["동영상", "영상", "다큐", "방송", "뉴스", "비디오", "movie", "video", "다큐멘터리"],
    "doc":   ["문서", "pdf", "보고서", "논문", "도서", "단행본", "보도자료"],
}

# 가중 강도 — 키워드 1개 매칭 시 final score 에 곱하는 boost
# 너무 크면 다른 도메인 매칭 완전 차단. 1.5 정도가 적정 (50% 가산).
DOMAIN_WEIGHT_BOOST = 0.5


def domain_relevance(query: str, domain: str) -> float:
    """쿼리에 도메인 키워드 매칭 시 boost 반환.

    Returns:
        1.0 + (매칭 키워드 수) × 0.5
        매칭 0 → 1.0 (영향 없음)
        매칭 1 → 1.5
        매칭 2 → 2.0
    """
    if not query or not domain:
        return 1.0
    q_lower = query.lower()
    kws = DOMAIN_KEYWORDS.get(domain, [])
    hits = sum(1 for kw in kws if kw.lower() in q_lower)
    return 1.0 + DOMAIN_WEIGHT_BOOST * hits


def global_percentile_rank(raw_score: float, all_raws: Iterable[float]) -> float:
    """5도메인 합산 풀에서 raw_score 의 percentile rank (0~1).

    도메인 무관 비교 가능: 글로벌 분포에서 상위 몇 % 인지.
    동순위 처리: ≤ 비교 (raw_score 보다 작거나 같은 비율).
    """
    arr = sorted(float(x) for x in all_raws)
    n = len(arr)
    if n == 0:
        return 0.0
    # binary search 보다 단순 count (n 작음, 보통 ≤500)
    rank = sum(1 for x in arr if x <= raw_score)
    return rank / n


def blended_confidence(raw_score: float, domain_pool: Iterable[float],
                        all_pool: Iterable[float], domain: str) -> float:
    """글로벌 percentile × 도메인 내 CMP 결합 — 도메인 무관 통합 confidence.

    공식:
        floor 미달 → 0.0  (무관 cut)
        glob_p = global_percentile_rank(raw, all_pool)
        loc_p  = sigmoid(α_d · z_d + β_d)         (도메인 내 z-score)
        final  = √(glob_p · loc_p)                (geometric mean)

    geometric mean 의미: 둘 중 하나라도 약하면 final 도 약함.
    - 글로벌 상위지만 도메인 내 평균 → 보통 (도메인이 우연히 raw 높음)
    - 도메인 내 1위지만 글로벌 하위 → 약함 (도메인 자체가 약매칭)
    - 둘 다 강하면 final 강함 (진짜 매칭)
    """
    floor = DOMAIN_RAW_FLOOR.get(domain, 0.5)
    if float(raw_score) < floor:
        return 0.0

    glob_p = global_percentile_rank(raw_score, all_pool)
    loc_p  = compute_cmp(raw_score, domain_pool, domain)
    return math.sqrt(max(glob_p * loc_p, 0.0))


def apply_blended_to_results(results_by_domain: dict[str, list[dict]],
                              raw_score_field: str = "similarity",
                              filter_below: Optional[float] = CMP_THRESHOLD_NONE,
                              query: str = "",
                              ) -> list[dict]:
    """5도메인 결과를 통합 confidence (blended) 로 합쳐서 단일 리스트 반환.

    Args:
        results_by_domain: {"doc": [...], "image": [...], ...}  도메인별 결과
        raw_score_field:   raw 점수 추출 필드 (default 'similarity' = 도메인별
                            가공 후 [0,1] 값. 없으면 'dense' / 'confidence' fallback)
        filter_below:      최종 confidence 가 이 값 미만이면 제외.

    Returns:
        통합된 단일 결과 리스트 (final confidence 내림차순 정렬, 무관 cut 됨).
        각 결과에 'cmp_blended', 'cmp_global', 'cmp_local' 필드 추가.
        'confidence' = cmp_blended (UI 표시 + ranking 기준).
    """
    # 1. 글로벌 풀 — 5도메인 합산 raw_score
    def _raw(r: dict) -> float:
        for f in (raw_score_field, "dense", "confidence"):
            v = r.get(f)
            if v is not None:
                return float(v)
        return 0.0

    all_raws: list[float] = []
    domain_pools: dict[str, list[float]] = {}
    for dom, lst in results_by_domain.items():
        pool = [_raw(r) for r in lst]
        domain_pools[dom] = pool
        all_raws.extend(pool)

    # 2. 각 결과에 blended confidence 계산 + 도메인 floor cut + query-aware boost
    out: list[dict] = []
    for dom, lst in results_by_domain.items():
        d_pool = domain_pools[dom]
        # 쿼리 → 도메인 키워드 매칭 → boost 1.0~2.0
        d_boost = domain_relevance(query, dom)
        for r in lst:
            raw = _raw(r)
            glob_p = global_percentile_rank(raw, all_raws)
            loc_p  = compute_cmp(raw, d_pool, dom)
            blended_base = blended_confidence(raw, d_pool, all_raws, dom)
            # query-aware: 쿼리에 도메인 키워드 매칭 시 final boost.
            # 1.0 (매칭 없음) ~ 2.0 (매칭 2개 이상) → min(1.0, …) cap.
            blended = min(1.0, blended_base * d_boost)
            r["cmp_global"]  = round(glob_p, 4)
            r["cmp_local"]   = round(loc_p, 4)
            r["cmp_blended"] = round(blended, 4)
            r["domain_boost"] = round(d_boost, 2)
            r["confidence"]  = round(blended, 4)  # ranking 기준
            r["similarity"]  = round(raw, 4)       # raw 보존
            if filter_below is not None and blended < filter_below:
                continue
            out.append(r)

    out.sort(key=lambda r: r.get("confidence", 0), reverse=True)
    return out


def compute_cmp(raw_score: float, candidates_pool: Iterable[float],
                domain: str) -> float:
    """단일 결과의 CMP 계산.

    Args:
        raw_score: 현재 결과의 raw 매칭 점수
        candidates_pool: 같은 쿼리의 모든 후보 raw_score (z-score 정규화용)
        domain: 'doc' | 'image' | 'video' | 'audio' | 'bgm'

    Returns:
        [0,1] 범위 CMP. 도메인 무관 비교 가능.
    """
    arr = [float(x) for x in candidates_pool]
    n = len(arr)
    if n == 0:
        return 0.0
    mu = sum(arr) / n
    if n > 1:
        var = sum((x - mu) ** 2 for x in arr) / n
        sigma = max(math.sqrt(var), 1e-6)
    else:
        sigma = 1.0
    z = (float(raw_score) - mu) / sigma
    alpha, beta = DOMAIN_CALIBRATION.get(domain, (1.0, 0.0))
    return 1.0 / (1.0 + math.exp(-(alpha * z + beta)))


def apply_cmp_to_results(results: list[dict], domain: str,
                         raw_score_field: str = "dense",
                         set_confidence: bool = True,
                         filter_below: Optional[float] = CMP_THRESHOLD_NONE
                         ) -> list[dict]:
    """도메인 결과 리스트에 CMP 일괄 적용.

    각 결과에 'cmp' 필드 추가, 'confidence' 를 CMP 로 갱신 (set_confidence=True).
    'similarity' 는 raw_score 보존 (UI 에 정보용 표시).

    Args:
        results: 도메인 결과 리스트 ([{"file_path":..., "dense":..., ...}, ...])
        domain: 도메인 라벨
        raw_score_field: pool 추출에 사용할 필드 (default 'dense' = raw cosine)
                          없으면 'confidence' fallback
        set_confidence: True 면 'confidence' 필드를 CMP 로 갱신 (ranking 기준)
        filter_below: CMP 가 이 값 미만이면 결과 제외. None 이면 필터링 안함.

    Returns:
        새 결과 리스트 (필터링 적용 시 길이 다름).
    """
    if not results:
        return results

    # raw_score pool 추출
    def _raw(r: dict) -> float:
        v = r.get(raw_score_field)
        if v is None or (isinstance(v, (int, float)) and v == 0):
            v = r.get("confidence", 0.0) or 0.0
        return float(v)

    pool = [_raw(r) for r in results]

    out: list[dict] = []
    for r in results:
        raw = _raw(r)
        cmp_val = compute_cmp(raw, pool, domain)
        if filter_below is not None and cmp_val < filter_below:
            continue
        r["cmp"] = round(cmp_val, 4)
        if set_confidence:
            # ranking 기준: CMP. 'similarity' 는 raw cosine 으로 정보용.
            r["confidence"] = round(cmp_val, 4)
            if "similarity" not in r or r.get("similarity") is None:
                r["similarity"] = round(raw, 4)
        out.append(r)
    return out


def cmp_threshold(level: str = "none") -> float:
    """판별 임계값 lookup."""
    return {
        "overwhelming": 0.95,
        "strong":       0.75,
        "moderate":     0.55,
        "weak":         0.40,
        "none":         CMP_THRESHOLD_NONE,
    }.get(level, CMP_THRESHOLD_NONE)
