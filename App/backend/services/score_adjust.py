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


def _meaningful_char_count(text: str) -> int:
    """알파넷 + 한글만 카운트 (특수문자/공백/이모지 제외)."""
    if not text:
        return 0
    s = text.strip()
    n = 0
    for c in s:
        if c.isalnum():
            n += 1
        elif "가" <= c <= "힯":  # 한글 음절
            n += 1
        elif "一" <= c <= "鿿":  # 한자
            n += 1
        elif "぀" <= c <= "ヿ":  # 히라가나·가타카나
            n += 1
    return n


def adjust_confidence(raw_conf: float, query: str = "") -> float:
    """raw_conf (0~1) → 사용자 친화 confidence (0~1).

    동작:
      1. 빈 쿼리 / 의미 없는 쿼리 (한글/영문/숫자 0글자) → max 30%
      2. 1글자 → max 55%
      3. 2글자 → 0.8 multiplier
      4. 3~4글자 → 0.92 multiplier
      5. 5글자+ → 정상

      6. Upper saturate 압축: 85%+ 영역을 85~97% 로 압축
         (강한 매칭들 사이 미세 차이 유지)
    """
    if raw_conf is None:
        return 0.0
    raw = max(0.0, min(1.0, float(raw_conf)))

    # 1. Edge case penalty
    n_meaningful = _meaningful_char_count(query)
    if n_meaningful == 0:
        return min(0.30, raw)
    elif n_meaningful == 1:
        return min(0.55, raw)
    elif n_meaningful == 2:
        edge_factor = 0.80
    elif n_meaningful <= 4:
        edge_factor = 0.92
    else:
        edge_factor = 1.0

    # 2. Upper compression — 90%+ saturate 완화
    if raw > 0.85:
        # raw 0.85 → 0.85, raw 1.0 → 0.97 (linear)
        compressed = 0.85 + (raw - 0.85) * (0.97 - 0.85) / (1.0 - 0.85)
    else:
        compressed = raw

    return max(0.0, min(1.0, compressed * edge_factor))


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
