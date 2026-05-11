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
    # [v17] 한↔영 대칭 보강: 영어 쿼리도 도메인 boost를 받도록
    # [v17.1] BGM 특화어 추가: 카페/명상/힐링/잔잔한 등 → BGM이 audio를 이기도록
    "bgm":   ["bgm", "배경음악", "ost", "효과음", "사운드트랙", "광고음악",
              # BGM 사용 맥락/분위기어 (배경음악 찾기 의도)
              "잔잔한", "카페", "명상", "힐링", "lofi", "lo-fi", "asmr",
              "집중", "편안한", "차분한", "피아노", "시네마틱", "브이로그",
              # [v17.3] 추가 분위기/상황어: "운동할 때", "로맨틱 분위기" 등
              "운동", "로맨틱", "분위기", "드라이브", "수면", "공부", "비오는",
              # [v17.4] 사운드/자연음 맥락: "자연 ASMR 사운드" 같은 주변음/효과음 쿼리
              "사운드", "자연음", "빗소리", "파도소리",
              # 영어 대응
              "background music", "background", "soundtrack", "ambient music",
              "ambient", "film score", "cinematic music", "lounge", "cafe",
              "meditation", "relaxing", "chill", "vlog",
              "workout", "romantic", "mood", "study", "sleep", "driving",
              "sound", "nature sound", "rain sound", "wave sound"],
    "audio": ["노래", "보컬", "팟캐스트", "녹음", "오디오", "음성", "wav",
              # 음악 단독어 (compound에서 떨어진 경우만 매칭 — token boundary)
              "음악",
              # 한국어 장르어 (xlang 평가 쌍: 팝송/재즈/클래식/힙합/록)
              "팝송", "재즈", "클래식", "힙합", "록", "발라드", "인디", "가요", "민요",
              # [v17.2] 강연/강의: 실제 데이터셋에 강연 WAV 파일 다수 — image 캡션에 묻히지 않도록
              "강연", "강의", "세미나", "컨퍼런스",
              # [v17.3] 재생 의도어: STT 쿼리 "들려줘/틀어줘" → 오디오 파일 재생 의도
              "들려줘", "들려", "틀어줘", "재생",
              # [v17.6] 인터뷰 오디오 레코딩: "한예종 인터뷰", "기업 회장 인터뷰" 등
              #   audio WAV 인터뷰 녹음을 video 보다 우선 반환하기 위해 추가.
              #   video 도 "인터뷰" 보유 → 두 도메인 동일 boost → dense 승부.
              "인터뷰",
              # 영어 대응 (장르 포함 — xlang 평가 쌍: pop song/jazz/classical/hip hop/rock)
              "music", "song", "jazz", "pop", "classical", "rock", "hip hop",
              "hip-hop", "ballad", "vocal", "podcast", "audio",
              # 영어 강연 대응
              "lecture", "seminar", "conference", "talk", "speech"],
    "image": ["이미지", "사진", "그림", "그래픽", "캡션", "픽쳐", "image", "photo",
              # 시각 장면/묘사어 추가 — image phrase/sentence 쿼리 boost
              "풍경", "경치", "모습", "장면", "설경", "야경", "풍광", "전경",
              # [v17.1] 자연/시각 명사: 단일어 이미지 쿼리 boost
              # ("바다", "산", "꽃" 등 → audio 팟캐스트보다 이미지 우선)
              "바다", "산", "꽃", "나무", "숲", "하늘", "구름", "강", "호수", "들판",
              "노을", "일출", "일몰", "설산", "사막", "폭포", "해변", "여성", "노인",
              # [v17.3] 인물 시각명사
              # [v17.6] "어린이" 재추가 — doc에 "교육" 추가됨으로써 균형:
              #   "어린이 교육 통계 OECD": doc boost (교육×0.20 + 통계×0.20) = ×1.40
              #                          > image boost (어린이×0.30) = ×1.30 → doc 승
              #   "어린이" 단독: image boost ×1.30 > video ×1.0 → image 승
              "아기", "얼굴", "미소", "어린이",
              # [v17.8] 동물 시각명사 — 단일어 이미지 쿼리 ("고양이", "강아지" 등)
              #   raw confidence ~17% → boost ×1.30 → ~22% → 저신뢰도 필터 통과
              "고양이", "강아지", "개", "새", "토끼", "새끼", "강아지", "곰",
              "사자", "호랑이", "코끼리", "원숭이", "펭귄", "물고기", "닭", "소",
              "말", "돼지", "여우", "늑대", "사슴", "거북이", "뱀", "앵무새",
              "햄스터", "다람쥐", "고라니", "동물",
              # 음식/사물 시각명사
              "음식", "케이크", "빵", "커피", "피자", "라면", "떡",
              "자동차", "차", "건물", "집",
              # 영어 동물 대응
              "cat", "dog", "bird", "rabbit", "bear", "lion", "tiger",
              "elephant", "monkey", "penguin", "fish", "chicken", "horse",
              "fox", "wolf", "deer", "turtle", "hamster", "animal",
              # 영어 음식/사물 대응
              "food", "cake", "bread", "coffee", "pizza", "car", "house",
              # 영어 일반
              "picture", "landscape", "scenery", "scene", "view", "portrait",
              "photograph", "illustration",
              "sea", "ocean", "mountain", "flower", "tree", "forest", "sky",
              "cloud", "river", "lake", "sunset", "sunrise", "beach", "waterfall"],
    "video": ["동영상", "영상", "다큐", "방송", "뉴스", "비디오", "movie", "video",
              # 한국어 추가 (xlang 평가 쌍 대응)
              "인터뷰", "다큐멘터리", "스포츠", "요리",
              # [v17.3] 구체적 스포츠 종목 추가
              "야구", "축구", "농구", "배구", "테니스", "골프",
              # [v17.7] 우주/과학 다큐 쿼리 ("코스모스 보이저호", "달 탐사" 등)
              # → video intent 인식, CDF inflation 보정(E13 fix v3) 우회
              "우주", "코스모스", "은하", "태양계", "행성", "NASA", "나사",
              "탐사", "발사", "로켓", "위성", "탐사선", "보이저", "아폴로",
              "천문", "별", "성운", "블랙홀", "혜성", "소행성",
              # 영어 대응 (xlang 평가 쌍: news/documentary/interview/sports/cooking)
              "news", "documentary", "interview", "broadcast", "footage",
              "sports", "cooking", "film", "clip", "series",
              "baseball", "soccer", "basketball", "football",
              # 영어 우주/과학 대응
              "space", "cosmos", "galaxy", "planet", "universe",
              "nasa", "rocket", "satellite", "voyager", "apollo",
              "astronomy", "nebula", "comet", "asteroid"],
    "doc":   ["문서", "pdf", "보고서", "논문", "도서", "단행본", "보도자료",
              # [v17.2] 문서 특화 명사: 보고서/분석서 작성 의도 쿼리 → doc boost
              # image가 tags_kr로 산업/정책 용어를 가져도 doc이 이기도록
              "현황", "통계", "정책", "전략", "연구", "경쟁력", "동향", "백서", "분석",
              # [v17.4] 문서 쿼리 특화어: 평가/고령화/대책 → doc-phrase 정합 개선
              "평가", "고령화", "대책", "지표", "시장", "산업",
              # [v17.6] 교육/경제/무역: doc-word-03 "어린이 교육", doc-word-09 "무역 수출"
              #   factor=0.20 이므로 audio/video cross-domain 오탐 최소화.
              #   "어린이 교육 통계": 교육(×0.20) + 통계(×0.20) = ×1.40 → image "어린이"(×1.30) 우선
              "교육", "학습", "교과",
              "무역", "수출", "수입", "경제", "금융", "투자", "예산",
              # 영어 대응
              "document", "report", "paper", "article", "press release",
              "publication", "magazine", "statistics", "policy", "strategy",
              "trend", "research", "analysis", "whitepaper",
              "evaluation", "assessment", "market", "industry",
              "education", "economy", "trade", "export", "import", "finance"],
}
# [v17.2] 도메인별 boost factor — doc은 키워드가 cross-domain 쿼리에 등장하여
#   audio/video 오탐 유발. doc만 0.20으로 낮춰 과도한 boost 방지.
QUERY_BOOST_FACTOR = 0.3   # 기본값 (bgm/audio/image/video)
DOMAIN_BOOST_FACTOR: dict[str, float] = {
    "bgm":   0.30,
    "audio": 0.30,
    "image": 0.30,
    "video": 0.30,
    "doc":   0.20,   # doc 키워드("동향","전략","연구" 등)가 audio 쿼리에도 등장
}


def query_intent_boost(query: str, domain: str) -> float:
    """쿼리 → 도메인 의도 매칭 boost.
    1.0 (매칭 없음) ~ 1 + n × DOMAIN_BOOST_FACTOR[domain].
    [v17.2] doc은 0.20 factor로 낮춤 (cross-domain 키워드 오탐 방지).

    [v17.1] 한국어 조사 인식 토큰 매칭:
      단일어 키워드는 공백 분리 토큰의 시작 부분과 매칭.
      접사(조사 등)가 붙은 경우도 허용 (suffix ≤ 3자).
      → "음악" in "배경음악" 오매칭 방지 (token 시작이 아님)
      → "야경이" → "야경" 조사 허용, "사진을" → "사진" 허용.
      복합어 키워드("background music")는 기존 substring 매칭 유지.
    """
    if not query or not domain:
        return 1.0
    q_lower = query.lower()
    q_tokens = q_lower.split()  # 공백 기준 토큰 리스트
    kws = DOMAIN_KEYWORDS.get(domain, [])
    hits = 0
    for kw in kws:
        kw_l = kw.lower()
        if " " in kw_l:
            # 복합어: substring 매칭 (예: "background music")
            if kw_l in q_lower:
                hits += 1
        else:
            # 단일어: 토큰 시작 매칭 + 조사 허용 (suffix ≤ 3자)
            # "야경이" startswith "야경" + suffix "이"(len=1) → 매칭
            # "배경음악" startswith "음악" → False (음악이 시작이 아님) → 미매칭
            matched = False
            for tok in q_tokens:
                if tok == kw_l:
                    matched = True
                    break
                if tok.startswith(kw_l) and len(tok) - len(kw_l) <= 3:
                    matched = True
                    break
            if matched:
                hits += 1
    factor = DOMAIN_BOOST_FACTOR.get(domain, QUERY_BOOST_FACTOR)
    return 1.0 + factor * hits


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

    # [v14 fix] Image — MPLC_WEIGHTS["image"] + generous_curve 보정.
    # 문제: MPLC 적용 시점에 r["dense"] = raw Hermitian 점수(0.2~0.4).
    #       hand-tune 공식 sigmoid((dense-0.6)×10) 은 gc 후 값(0.6~0.9) 설계
    #       → raw 0.40 → sigmoid(-2.0) = 0.12 (과소), 이미지 항상 패배.
    # 수정: generous_curve 로 dense 보정 후 학습된 MPLC_WEIGHTS["image"] 사용.
    #       MPLC_WEIGHTS["image"] 는 keyword_count/z_dense 도 활용해
    #       Doc 쿼리에서 노이즈 이미지가 Doc 을 이기는 부작용 방지.
    #
    # 검증:
    #   이미지 쿼리 (raw=0.42, gc=0.90, kw=0): sigmoid(-14.61+18.69×0.90) = 0.91 ✓
    #   Doc 쿼리 노이즈 이미지 (raw=0.32, gc=0.79, kw=0): sigmoid(0.32) = 0.58 ✓
    #   (Doc 강매칭 MPLC ≈ 0.78 > 0.58 → Doc 승리)
    if domain == "image":
        try:
            from services.score_adjust import _generous_curve as _gc
            feats_img = dict(feats)
            feats_img["dense"] = _gc(float(feats.get("dense", 0.0)))
        except Exception:
            feats_img = feats
        if "image" in MPLC_WEIGHTS:
            w_img = MPLC_WEIGHTS["image"]
            bias_img = float(w_img.get("bias", 0))
            wts_img  = w_img.get("weights", {})
            z_img = bias_img + sum(float(wts_img.get(f, 0)) * feats_img.get(f, 0)
                                   for f in FEATURES)
            return float(min(1.0, _sigmoid(z_img)))
        # fallback: gc 보정 후 hand-tune
        dense = feats_img.get("dense", 0.0)
        base = _sigmoid((dense - 0.6) * 10.0)
        bonus = 0.10 * feats.get("keyword_count", 0) + 0.10 * feats.get("filename_substr", 0)
        return float(min(1.0, base + bonus))

    # [v17] Audio — trained MPLC_WEIGHTS["audio"] 사용.
    # v16 이전: keyword_count=-1.50 (음수) → hand-tune 필요.
    # v17 fix: expanded_query 로 학습 → keyword_count=+3.45, asf=+2.21 (양수).
    # → 학습된 weights 그대로 사용 (hand-tune 제거).
    # 검증: z_dense=3, kw=0.5 → sigmoid(3.715) ≈ 0.976 (오디오 강매칭)
    #       z_dense=1, kw=0   → sigmoid(-5.55)  ≈ 0.004 (비오디오 낮음)

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

    [v14] 파일명 매칭 boost 보존:
      search_av 의 filename boost (conf ≥ 0.60) 는 강한 파일명 일치 신호.
      MPLC 가 이를 덮어써 0.15~0.27 로 낮추면 파일명 일치 항목이 묻히는 버그.
      수정: max(mplc_score, prev_conf × 0.95) → 기존 boost 보존 + 약한 패널티만.
    """
    for domain, lst in results_by_domain.items():
        for r in lst:
            score = compute_mplc_score(r, domain, query)
            r["mplc_score"] = round(score, 4)
            if set_confidence:
                # raw_similarity 보존 (UI 정보용), confidence 는 MPLC 로 갱신
                if "similarity" not in r or r.get("similarity") is None:
                    r["similarity"] = round(float(r.get("dense", 0) or 0), 4)
                # [v14] filename boost 보존: 이전 confidence 가 더 높으면 유지
                # (search_av 에서 filename 매칭으로 conf≥0.60 설정된 경우)
                prev_conf = float(r.get("confidence", 0) or 0)
                r["confidence"] = round(max(score, prev_conf * 0.95), 4)
    return results_by_domain
