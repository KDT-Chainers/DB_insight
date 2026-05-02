"""자연어 BGM 쿼리 파서.

music_search_20260422/nlp_query.py 에서 ParsedQuery + mood synonym 부분을 포팅.
ACR boost 텍스트는 제거 (외부 의존 없는 단순화).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 무드 동의어 — librosa rule-based tag 와 매칭
MOOD_SYNONYMS: dict[str, list[str]] = {
    "calm":     ["잔잔", "차분", "평온", "calm", "relax", "잔잔한", "slow"],
    "upbeat":   ["신나", "활기", "빠른", "upbeat", "energetic", "댄스", "fast"],
    "dark":     ["어두", "무드", "dark", "무거운", "저음", "dark-timbre"],
    "bright":   ["밝", "화사", "bright", "경쾌", "bright-timbre"],
    "melodic":  ["선율", "멜로디", "melodic", "서정"],
    "rhythmic": ["리듬", "비트", "rhythmic", "그루브"],
    "quiet":    ["조용", "잔잔", "quiet"],
    "loud":     ["크게", "강한", "loud", "거센"],
}

_BAD_LEAD_FOR_NORAE = frozenset({
    "잔잔한", "신나는", "슬픈", "조용한", "좋은",
    "이", "그", "내", "우리", "추천",
})

_NAME_ONLY_BLOCK = (
    "배경", "동영상", "영상", "찾아", "음악", "노래",
    "비슷", "느낌", "분위기", "강의", "대화",
    "없는", "없어", "들어간", "있는",
    "알려", "추천", "곡", "가수", "아티스트", "artist",
)


@dataclass
class ParsedQuery:
    raw: str
    artist_hint: str | None = None
    title_hint: str | None = None
    broad_artist_search: bool = False
    text_for_clap: str = ""
    mood_boosts: list[str] = field(default_factory=list)


def _try_name_only_artist(q: str) -> str | None:
    s = q.strip()
    if len(s) < 2 or len(s) > 80:
        return None
    if any(tok in s for tok in _NAME_ONLY_BLOCK):
        return None
    if s in _BAD_LEAD_FOR_NORAE or s.lower() in _BAD_LEAD_FOR_NORAE:
        return None
    if not re.search(r"[a-zA-Z가-힣]", s):
        return None
    return s


def parse(query: str) -> ParsedQuery:
    """자연어 쿼리 → ParsedQuery."""
    q = (query or "").strip()
    artist_hint: str | None = None
    title_hint: str | None = None

    # 가수 XXX / artist: XXX
    m = re.search(
        r"(?:가수|artist|아티스트)\s*[:：]?\s*['\"]?([^'\"]+?)['\"]?(?:\s|$|으로|로|를|을)",
        q, re.IGNORECASE,
    )
    if m:
        artist_hint = m.group(1).strip()
    else:
        m2 = re.search(r"['\"]([^'\"]{2,40})['\"]\s*(?:의\s*)?(?:곡|노래|음악)", q)
        if m2:
            artist_hint = m2.group(1).strip()

    # "<아티스트> 음악이 배경/있는/들어간"
    if not artist_hint:
        for pat in (
            r"^(.+?)\s*음악(?:이|가)\s*배경",
            r"^(.+?)\s*음악이\s*있는",
            r"^(.+?)\s*음악이\s*들어간",
        ):
            mm = re.search(pat, q, re.IGNORECASE)
            if mm:
                cand = mm.group(1).strip()
                if 1 <= len(cand) <= 120:
                    artist_hint = cand
                break

    # "X 노래 찾아줘"
    if not artist_hint:
        mm = re.search(r"^(.{2,80}?)\s+노래", q.strip(), re.IGNORECASE)
        if mm:
            cand = mm.group(1).strip()
            if (
                cand
                and cand not in _BAD_LEAD_FOR_NORAE
                and cand.lower() not in _BAD_LEAD_FOR_NORAE
            ):
                artist_hint = cand

    # 곡명: "<아티스트>의 <제목>이/가 배경"
    mt = re.search(r"의\s+(.+?)(?:가|이)\s+배경", q)
    if mt:
        title_hint = mt.group(1).strip()
        if len(title_hint) > 120:
            title_hint = None
        if not artist_hint:
            before = q[: mt.start()].strip()
            if 1 <= len(before) <= 120:
                artist_hint = before

    mood_boosts: list[str] = []
    low = q.lower()
    for mood, words in MOOD_SYNONYMS.items():
        if any(w in q or w.lower() in low for w in words):
            mood_boosts.append(mood)

    if not artist_hint:
        artist_hint = _try_name_only_artist(q)

    broad = bool(artist_hint and not title_hint)

    extra = " ".join(w for m in mood_boosts for w in MOOD_SYNONYMS.get(m, []))
    text_for_clap = f"{q} {extra}".strip()

    return ParsedQuery(
        raw=q,
        artist_hint=artist_hint,
        title_hint=title_hint,
        broad_artist_search=broad,
        text_for_clap=text_for_clap,
        mood_boosts=mood_boosts,
    )
