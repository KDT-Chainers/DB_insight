"""규칙 기반 쿼리 재작성.

LLM 없이 경량화 원칙 유지. 사용자 한/영 혼합 쿼리 관례에 맞춤.

주요 변환:
  · 한글만 있는 쿼리 → (간단 사전) 영어 토큰 병기
  · 영어만 있는 쿼리 → 한글 보조어 병기
  · 불용어/수식어 제거로 핵심 키워드 부각
"""
from __future__ import annotations

import re

# 의도적으로 소규모 사전만 — 확장 필요 시 도메인별 사전으로 분리.
_KO_EN = {
    "마이클 조던": "Michael Jordan",
    "농구": "basketball",
    "덩크": "dunk",
    "슛":   "shot",
    "경제": "economy",
    "투자": "investment",
    "주식": "stock",
    "강의": "lecture",
    "뉴스": "news",
    "음악": "music",
    "노래": "song",
    "기타": "guitar",
    "게임": "game",
    "영화": "movie",
    "인공지능": "AI artificial intelligence",
    "창업": "startup",
    "실리콘밸리": "Silicon Valley",
    "물리학": "physics",
    "수학": "mathematics",
    "역사": "history",
}

_EN_KO = {v.lower(): k for k, v in _KO_EN.items()}

_HANGUL = re.compile(r"[\uac00-\ud7a3]")
_ASCII  = re.compile(r"[A-Za-z]")

_FILLERS = {
    "에 대해서", "대한", "관련", "좀", "에 대해", "~에", "그", "정말",
    "좋은", "보여주세요", "알려주세요", "설명해주세요", "를", "을", "이",
    "가", "은", "는", "의",
}


def _strip_fillers(text: str) -> str:
    for f in sorted(_FILLERS, key=len, reverse=True):
        text = text.replace(f, " ")
    return re.sub(r"\s+", " ", text).strip()


def rewrite(query: str) -> str:
    """한/영 상호 보강 + 수식어 제거. 원 쿼리 토큰은 보존."""
    q = query.strip()
    if not q:
        return q

    has_ko = bool(_HANGUL.search(q))
    has_en = bool(_ASCII.search(q))

    extras: list[str] = []

    if has_ko and not has_en:
        for ko, en in _KO_EN.items():
            if ko in q:
                extras.append(en)
    elif has_en and not has_ko:
        for en, ko in _EN_KO.items():
            if re.search(rf"\b{re.escape(en)}\b", q, flags=re.IGNORECASE):
                extras.append(ko)
    # 이미 혼합이면 확장 생략 (사용자 의도 존중)

    core = _strip_fillers(q)
    if extras:
        return f"{core} {' '.join(extras)}".strip()
    return core
