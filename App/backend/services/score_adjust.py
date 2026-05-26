"""5도메인 통합 confidence 조정 — Edge case + saturate 완화.

raw_conf (z-score CDF 결과) 를 받아 사용자 친화 confidence 로 변환:
  1. Edge case query 페널티 — 의미 없는 짧은/특수문자 쿼리는 강제로 낮춤
  2. Upper saturate 압축 — 90%+ 영역을 분산 (90~95% 범위로)
  3. σ_null floor 보정은 calibration 단계에서 처리 (이 파일과 무관)

Doc/Img/Movie/Rec/BGM 모두 동일 매핑 적용.

호출 위치:
  routes/bgm.py     — bgm.search() 결과 후처리
  routes/search.py  — trichef hits 후처리
  routes/trichef.py — trichef search/search_av 결과 후처리
"""
from __future__ import annotations
import math
from typing import Iterable


def _classify_query(text: str) -> dict:
    """글자 종류별 카운트 — 의미 있는 글자만 정밀 분류.

    Buckets:
      alpha    — 라틴 알파벳 (A-Z, a-z 등 .isalpha()=True 면서 다른 카테고리 X)
      digit    — 숫자 (0-9 등)
      hangul   — 한글 음절 (U+AC00-D7AF)  ← '가'~'힯'
      cjk      — 한자 (U+4E00-9FFF) + 히라가나/가타카나 (U+3040-30FF)
      other    — 한글 자모 (U+3130-318F: ㄱㄴㅎ 등) + 특수문자 + 공백 + 이모지

    Hangul jamo (ㄱㅎㅋ 등) 는 isalpha()=True 라서 "의미 있는 글자" 처리되면
    "ㅋㅋ" 같은 무의미 입력이 점수 페널티 못 받음 → 명시적으로 other 분류.
    """
    counts = {"alpha": 0, "digit": 0, "hangul": 0, "cjk": 0, "other": 0}
    if not text:
        return {**counts, "meaningful": 0, "len": 0}
    s = text.strip()
    for c in s:
        cp = ord(c)
        if c.isdigit():
            counts["digit"] += 1
        elif 0xAC00 <= cp <= 0xD7AF:        # 한글 음절 가-힯
            counts["hangul"] += 1
        elif 0x4E00 <= cp <= 0x9FFF:        # 한자 (CJK Unified Ideographs)
            counts["cjk"] += 1
        elif 0x3040 <= cp <= 0x30FF:        # 히라가나/가타카나
            counts["cjk"] += 1
        elif 0x3130 <= cp <= 0x318F:        # 한글 호환 자모 (ㄱㅎㅋ 등) — 무의미
            counts["other"] += 1
        elif c.isalpha():                   # 라틴 알파벳 등 (Hangul jamo 는 위에서 거름)
            counts["alpha"] += 1
        else:
            counts["other"] += 1
    counts["meaningful"] = counts["alpha"] + counts["hangul"] + counts["cjk"]
    counts["len"] = len(s)
    return counts


def _generous_curve(raw: float) -> float:
    """CLIP/SigLIP2/BGE-M3 등 raw cosine [0.0, 0.6] 의 좁은 범위를
    사용자 친화 [0%, 99%] 로 공격적 확장.

    배경:
      SigLIP2 image cosine: 강한 매칭도 0.25~0.35 범위 (대부분 0.30 이하)
      BGE-M3 doc cosine:    강한 매칭 0.40~0.60
      CLAP audio cosine:    강한 매칭 0.30~0.55

    매핑 (조각별 선형, 모델 분포에 맞춰 공격적):
      0.00 → 0%
      0.10 → 30%
      0.25 → 70%   ← SigLIP2 보통 매칭
      0.40 → 90%   ← BGE-M3 의미 매칭
      0.60 → 98%   ← 매우 강한 매칭
      1.00 → 99%
    """
    x = max(0.0, min(1.0, raw))
    if x < 0.10:
        return x * 3.0                                # 0~30%
    elif x < 0.25:
        return 0.30 + (x - 0.10) * (0.40 / 0.15)      # 30~70%
    elif x < 0.40:
        return 0.70 + (x - 0.25) * (0.20 / 0.15)      # 70~90%
    elif x < 0.60:
        return 0.90 + (x - 0.40) * (0.08 / 0.20)      # 90~98%
    else:
        return min(1.0, 0.98 + (x - 0.60) * 0.025)    # 98~99%


def hermitian_sort_curve(h: float) -> float:
    """[순위 보존 전용] v1 hermitian curve — _sort_key 에서 ds 계산에만 사용.

    표시용 hermitian_display_curve(v2)와 분리되어 곡선 튜닝이 ranking 에 영향
    주지 않도록 보호한다. v24 검증 시점의 정렬 결과를 그대로 재현.
    """
    x = max(0.0, min(1.0, float(h)))
    if x < 0.10:
        return 0.05
    elif x < 0.20:
        return 0.05 + (x - 0.10) * (0.15 / 0.10)    #  5% → 20%
    elif x < 0.286:
        return 0.20 + (x - 0.20) * (0.18 / 0.086)   # 20% → 38%
    elif x < 0.350:
        return 0.38 + (x - 0.286) * (0.32 / 0.064)  # 38% → 70%
    elif x < 0.450:
        return 0.70 + (x - 0.350) * (0.22 / 0.10)   # 70% → 92%
    else:
        return min(0.97, 0.92 + (x - 0.450) * 0.10) # 92% → 97%


def hermitian_display_curve(h: float) -> float:
    """Hermitian 복합 점수 전용 표시 커브 (image 도메인).

    [v2 cross-modal 재캘리브레이션 — 2026-05-26]
    이전 v1 은 image-to-image null 분포(μ=0.286)에 anchor 되어 있어, text→image
    cross-modal cosine(SigLIP2)가 본질적으로 좁은 분포(0.10~0.30)임에도 양성
    이미지가 "무관 기준선(38%)"보다 낮게 표시되던 misleading 문제 발생.
      예: "햄버거" 검색 → 실제 햄버거 raw H≈0.17 → 곡선상 16% 표시
          (사용자: "유사도 20% 도 안되는데 맞나요?")

    cross-modal raw H 실측 분포 기반 재매핑:
      H ≤ 0.10  →  10%  (최하한)
      H = 0.17  →  55%  (cross-modal 양성, "햄버거" 매칭 수준)
      H = 0.25  →  75%
      H = 0.35  →  88%  (강한 매칭)
      H = 0.50  →  96%
      H ≥ 0.60  →  99%  (상한)

    주의: 본 곡선은 표시(유사도 UI) 전용. 순위 계산(_sort_key)은
    raw_dense 를 직접 사용하므로 곡선 변경이 ranking 에 영향 없음.
    """
    x = max(0.0, min(1.0, float(h)))
    if x < 0.10:
        return 0.10
    elif x < 0.17:
        return 0.10 + (x - 0.10) * (0.45 / 0.07)    # 10% → 55%
    elif x < 0.25:
        return 0.55 + (x - 0.17) * (0.20 / 0.08)    # 55% → 75%
    elif x < 0.35:
        return 0.75 + (x - 0.25) * (0.13 / 0.10)    # 75% → 88%
    elif x < 0.50:
        return 0.88 + (x - 0.35) * (0.08 / 0.15)    # 88% → 96%
    else:
        return min(0.99, 0.96 + (x - 0.50) * 0.06)  # 96% → 99%


def adjust_confidence(raw_conf: float, query: str = "") -> float:
    """raw_conf (0~1) → 사용자 친화 confidence (0~1).

    Edge case 페널티 (의미 없는 쿼리만 격리):
      meaningful=0 + digit=0      → cap 30% (빈 쿼리, 자모, 특수문자, 이모지)
      meaningful=0 + digit≥1      → cap 40% (숫자만 — '1234')
      meaningful=1                → cap 55%
      meaningful≥2                → 정상 처리 (한글 2글자 '산업', '교육' 등 의미 완전)

    Generous curve:
      raw 0.30 → 50%, raw 0.40 → 70%, raw 0.50 → 85%, raw 0.60+ → 95%+
      (CLIP-family 모델의 좁은 cosine 분포를 친화 % 로 확장)
    """
    if raw_conf is None:
        return 0.0
    raw = max(0.0, min(1.0, float(raw_conf)))

    # 1. Edge case 격리만 — 의미 있는 글자 ≥ 2 면 페널티 없음
    q = _classify_query(query)
    n_meaningful = q["meaningful"]

    if n_meaningful == 0:
        if q["digit"] >= 1:
            return min(0.40, _generous_curve(raw))
        return min(0.30, _generous_curve(raw))
    elif n_meaningful == 1:
        return min(0.55, _generous_curve(raw))

    # 2. 의미 있는 쿼리 (2+ 글자) → generous curve 적용
    return _generous_curve(raw)


def apply_query_penalty(cdf_conf: float, query: str = "") -> float:
    """TRI-CHEF처럼 이미 z-score CDF [0,1]로 정규화된 confidence에
    쿼리 품질 페널티만 적용 (generous_curve 이중 적용 금지).

    의미 없는 쿼리(자모, 특수문자, 짧은 숫자)일 때만 상한을 낮춤.
    정상 쿼리(의미 있는 글자 ≥2)는 그대로 통과.
    """
    if cdf_conf is None:
        return 0.0
    raw = max(0.0, min(1.0, float(cdf_conf)))
    q = _classify_query(query)
    n = q["meaningful"]
    if n == 0:
        return min(0.30 if q["digit"] == 0 else 0.40, raw)
    elif n == 1:
        return min(0.55, raw)
    return raw


def adjust_confidences(items: Iterable[dict], query: str,
                       conf_field: str = "confidence") -> None:
    """리스트 내 각 dict 의 confidence 필드를 in-place 갱신.

    items 의 각 요소가 dict 면 conf_field 키 갱신.
    """
    for it in items:
        if not isinstance(it, dict):
            continue
        if conf_field in it:
            it[conf_field] = round(adjust_confidence(it[conf_field], query), 4)
