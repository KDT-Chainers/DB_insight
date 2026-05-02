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


def adjust_confidence(raw_conf: float, query: str = "") -> float:
    """raw_conf (0~1) → 사용자 친화 confidence (0~1).

    Edge case 페널티 매트릭스:
      meaningful=0 + digit=0      → cap 30% (빈 쿼리, 자모/특수문자 only)
      meaningful=0 + digit≥1      → cap 40% (숫자만 — '1234')
      meaningful=1                → cap 55%
      meaningful=2                → ×0.80
      meaningful=3~4              → ×0.92
      meaningful=5+               → ×1.0

    Upper saturate 압축:
      raw 0.85+ → 0.85~0.97 범위로 압축 (강한 매칭 사이 차이 가시화)
    """
    if raw_conf is None:
        return 0.0
    raw = max(0.0, min(1.0, float(raw_conf)))

    # 1. Edge case penalty (정밀 분류)
    q = _classify_query(query)
    n_meaningful = q["meaningful"]

    if n_meaningful == 0:
        if q["digit"] >= 1:
            return min(0.40, raw)   # 숫자만 ('1234' 등)
        return min(0.30, raw)        # 빈 쿼리, 자모, 특수문자, 이모지
    elif n_meaningful == 1:
        return min(0.55, raw)
    elif n_meaningful == 2:
        edge_factor = 0.80
    elif n_meaningful <= 4:
        edge_factor = 0.92
    else:
        edge_factor = 1.0

    # 2. Upper compression — saturate 완화
    if raw > 0.85:
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
