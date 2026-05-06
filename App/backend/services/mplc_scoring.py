"""MPLC (Multi-Phase Linear Combination) — 학습된 weights 기반 통합 ranking.

XRD Bragg peak Rietveld refinement 비유:
  단일 raw cosine = 단일 wavelength (relevant/irrelevant 분리 불가)
  → multi-feature linear combination = 다중 wavelength 선형 조합
     (Cover's theorem + Bayesian logistic regression)

사용:
    from services.mplc_scoring import compute_mplc_score, apply_mplc_to_results
    score = compute_mplc_score(result_dict, "doc", query)        # ∈ [0,1]
    apply_mplc_to_results(results_by_domain, query)              # in-place

학습 결과 (CV AUC):
    doc: 0.972, image: 0.924, video: 0.986, audio: 0.989, bgm: 0.912
"""
from __future__ import annotations
import math
from typing import Optional

try:
    from services.mplc_weights import MPLC_WEIGHTS, FEATURES
except ImportError:
    MPLC_WEIGHTS = {}
    FEATURES = ["dense", "sparse", "asf", "rerank",
                "keyword_count", "filename_substr", "z_dense"]


# [v16] Query-aware domain boost — 자연어 쿼리에서 도메인 의도 추출.
#   예: "잔잔한 배경음악 BGM" → bgm 키워드 매칭 → bgm score ×1.3.
#   곱셈 형태 → 다른 도메인 매칭에 영향 X (절대 boost).
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "bgm":   ["bgm", "배경음악", "ost", "효과음", "사운드트랙", "광고음악"],
    "audio": ["음악", "노래", "보컬", "팟캐스트", "녹음", "오디오", "음성", "wav"],
    "image": ["이미지", "사진", "그림", "그래픽", "캡션", "픽쳐", "image", "photo"],
    "video": ["동영상", "영상", "다큐", "방송", "뉴스", "비디오", "movie", "video"],
    "doc":   ["문서", "pdf", "보고서", "논문", "도서", "단행본", "보도자료"],
}
QUERY_BOOST_FACTOR = 0.3   # 키워드 1개 매칭 → ×1.3


def query_intent_boost(query: str, domain: str) -> float:
    """쿼리 → 도메인 의도 매칭 boost.
    1.0 (매칭 없음) ~ 1 + n × QUERY_BOOST_FACTOR.
    """
    if not query or not domain:
        return 1.0
    q_lower = query.lower()
    kws = DOMAIN_KEYWORDS.get(domain, [])
    hits = sum(1 for kw in kws if kw.lower() in q_lower)
    return 1.0 + QUERY_BOOST_FACTOR * hits


# [v16] '없음' / 노이즈 제거 임계값. 측정한 MPLC 분포에서:
#   top 75% ≥ 0.047, top 90% ≥ 0.017 → 0.1 이상이면 의미 있는 매칭.
MPLC_NOISE_THRESHOLD = 0.10


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def extract_features(r: dict, query: str) -> dict:
    """결과 dict 에서 7 features 추출."""
    fn = (r.get("file_name") or "").lower()
    snippet = (r.get("snippet") or "").lower()
    fp = (r.get("file_path") or "").lower()
    q_lower = query.lower().strip()
    q_tokens = [t for t in query.split() if len(t) >= 2]

    if q_tokens:
        hay = fn + " " + snippet + " " + fp
        hits = sum(1 for t in q_tokens if t.lower() in hay)
        f5 = hits / len(q_tokens)
    else:
        f5 = 0.0

    f6 = 1.0 if q_lower and q_lower in (fn + " " + fp) else 0.0

    return {
        "dense": float(r.get("dense", 0) or 0),
        "sparse": float(r.get("lexical", 0) or r.get("sparse", 0) or 0),
        "asf": float(r.get("asf", 0) or 0),
        "rerank": float(r.get("rerank_score", 0) or 0),
        "keyword_count": float(f5),
        "filename_substr": float(f6),
        "z_dense": float(r.get("z_score", 0) or 0),
    }


def compute_mplc_score(r: dict, domain: str, query: str) -> float:
    """학습된 weights 로 final score 계산 (도메인 무관 [0,1]).

    Returns:
        sigmoid(bias + Σ wᵢ · featureᵢ)  ∈ [0, 1]
        domain weights 없으면 confidence fallback.

    [v13.1] image 도메인 hand-tune:
      학습된 weights 의 image 도메인은 z_dense feature 의미 불일치로
      극단적 분리 (real_cat_31 dense=0.85 → mplc 0.001 부작용).
      image 는 단순 dense 기반 sigmoid 로 대체:
        score = sigmoid((dense - 0.6) × 10)
        + 키워드/파일명 매칭 bonus 0.1
      dense=0.85 → 0.92, dense=0.65 → 0.62, dense=0.55 → 0.38.
    """
    feats = extract_features(r, query)

    # Image hand-tune (학습 weights overfit 회피)
    if domain == "image":
        dense = feats.get("dense", 0.0)
        base = _sigmoid((dense - 0.6) * 10.0)
        bonus = 0.10 * feats.get("keyword_count", 0) + \
                0.10 * feats.get("filename_substr", 0)
        return float(min(1.0, base + bonus))

    if domain not in MPLC_WEIGHTS:
        return float(r.get("confidence", 0) or 0)

    w = MPLC_WEIGHTS[domain]
    bias = float(w.get("bias", 0))
    weights = w.get("weights", {})
    z = bias
    for f in FEATURES:
        z += float(weights.get(f, 0)) * feats.get(f, 0)
    return _sigmoid(z)


def apply_mplc_to_results(results_by_domain: dict, query: str,
                          set_confidence: bool = True) -> dict:
    """5도메인 결과에 MPLC score 일괄 적용 (in-place).

    각 결과에 'mplc_score' 추가 + set_confidence=True 면 'confidence' 갱신.
    Returns: 입력 results_by_domain 그대로.
    """
    for domain, lst in results_by_domain.items():
        for r in lst:
            score = compute_mplc_score(r, domain, query)
            r["mplc_score"] = round(score, 4)
            if set_confidence:
                # raw_similarity 보존 (UI 정보용), confidence 는 MPLC 로 갱신
                if "similarity" not in r or r.get("similarity") is None:
                    r["similarity"] = round(float(r.get("dense", 0) or 0), 4)
                r["confidence"] = round(score, 4)
    return results_by_domain
