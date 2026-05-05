"""자연어 BGM 쿼리 파서.

music_search_20260422/nlp_query.py 에서 ParsedQuery + mood synonym 부분을 포팅.
ACR boost 텍스트는 제거 (외부 의존 없는 단순화).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 무드 동의어 — librosa rule-based tag 와 매칭 + 다국어 확장
MOOD_SYNONYMS: dict[str, list[str]] = {
    # 템포 / 에너지
    "calm":       ["잔잔", "차분", "평온", "calm", "relax", "relaxed", "잔잔한",
                   "slow", "peaceful", "soothing", "gentle", "soft", "mellow",
                   "느린", "여유", "부드러운", "편안", "안정",
                   "힐링", "치유", "명상", "요가", "healing", "meditation"],
    "upbeat":     ["신나", "활기", "빠른", "upbeat", "energetic", "댄스", "fast",
                   "exciting", "lively", "cheerful", "happy", "joyful", "fun",
                   "festive", "dynamic", "pumping", "groovy",
                   "신나는", "활기찬", "경쾌", "흥겨운", "흥분", "빠르고"],
    "dark":       ["어두", "무드", "dark", "무거운", "저음", "dark-timbre",
                   "gloomy", "somber", "heavy", "serious", "tense", "intense",
                   "mysterious", "haunting", "dramatic", "ominous",
                   "어두운", "무거운", "긴장", "심각", "신비",
                   "공포", "두려운", "horror", "scary", "threatening", "suspense", "서스펜스"],
    "bright":     ["밝", "화사", "bright", "경쾌", "bright-timbre",
                   "cheerful", "light", "positive", "optimistic", "sunny",
                   "밝은", "환한", "명랑", "가벼운", "긍정적"],
    "melodic":    ["선율", "멜로디", "melodic", "서정",
                   "lyrical", "beautiful", "romantic", "emotional", "sentimental",
                   "감성", "감동", "서정적", "아름다운", "로맨틱", "叙情"],
    "rhythmic":   ["리듬", "비트", "rhythmic", "그루브",
                   "groove", "beat", "percussive", "driving", "pulsing",
                   "리드미컬", "비트감", "박자", "그루브"],
    "quiet":      ["조용", "잔잔", "quiet", "silent", "soft",
                   "subtle", "hushed", "minimal", "background",
                   "조용한", "은은한", "잔잔히", "배경"],
    "loud":       ["크게", "강한", "loud", "거센", "powerful",
                   "bold", "forceful", "aggressive", "강렬", "웅장"],
    # 장르 / 스타일
    "jazz":       ["재즈", "jazz", "jazzband", "swing", "blues", "스윙"],
    "classical":  ["클래식", "classical", "orchestra", "orchestral", "symphony",
                   "piano", "violin", "chamber", "baroque", "romantic",
                   "오케스트라", "교향곡", "피아노", "바이올린"],
    "rock":       ["록", "rock", "guitar", "electric", "band", "metal",
                   "기타", "밴드"],
    "pop":        ["팝", "pop", "popular", "kpop", "k-pop"],
    "hip_hop":    ["힙합", "hip hop", "rap", "hiphop", "랩", "비트박스"],
    "electronic": ["전자", "electronic", "edm", "techno", "synth", "ambient",
                   "electronica", "일렉트로닉", "신스"],
    "folk":       ["포크", "folk", "acoustic", "country", "어쿠스틱"],
    "rnb":        ["R&B", "rnb", "soul", "funk", "소울", "펑크"],
    "ballad":     ["발라드", "ballad", "slow ballad", "love song", "러브송"],
    "trot":       ["트로트", "trot", "뽕짝"],
    # 용도 / 분위기 (영상 BGM 관점)
    "news":       ["뉴스", "news", "방송", "broadcast", "reporting"],
    "sports":     ["스포츠", "sports", "경기", "game", "match", "응원", "cheering"],
    "cinematic":  ["영화", "cinematic", "film", "드라마틱", "dramatic", "epic",
                   "웅장한", "장엄", "다큐", "다큐멘터리", "documentary",
                   "예고편", "trailer", "preview", "grand"],
    "corporate":  ["회사", "기업", "corporate", "business", "professional",
                   "발표", "presentation", "광고", "CF", "commercial",
                   "advertisement", "인트로", "intro", "아웃트로", "outro"],
    "emotional":  ["감동", "슬픈", "sad", "emotional", "touching", "tears",
                   "눈물", "슬픔", "애잔", "heartfelt",
                   "그리움", "그리운", "longing", "nostalgic", "설레", "설레는",
                   "보고싶다", "아련", "tender", "poignant"],
    "funny":      ["재미", "funny", "playful", "quirky", "comical", "코믹",
                   "유머", "웃긴", "귀여운", "cute", "adorable", "lighthearted"],
    # 신규 카테고리
    "dreamy":     ["몽환", "몽환적", "환상", "꿈같은", "dreamy", "ethereal",
                   "atmospheric", "ambient", "floating", "surreal",
                   "신비로운", "청량", "청량한", "refreshing", "crisp", "airy"],
    "retro":      ["레트로", "복고", "빈티지", "retro", "vintage", "nostalgic",
                   "oldschool", "classic feel", "80s", "90s", "추억",
                   "과거", "향수"],
    "lofi":       ["로파이", "로우파이", "lo-fi", "lofi", "chill hop", "chillhop",
                   "chill", "laid back", "low-fi", "study music",
                   "공부", "카페음악", "cafe music"],
    "nature":     ["자연", "숲", "새소리", "바다", "파도", "비", "빗소리",
                   "nature", "forest", "birds", "ocean", "waves", "rain",
                   "rainfall", "stream", "flowing water", "개울", "시냇물",
                   "풀소리", "바람소리", "wind"],
    # 악기
    "piano":      ["피아노", "piano"],
    "guitar":     ["기타", "guitar", "acoustic guitar", "electric guitar"],
    "violin":     ["바이올린", "violin", "strings", "현악"],
    "drums":      ["드럼", "drums", "percussion", "타악기"],
    "bass":       ["베이스", "bass"],
    "flute":      ["플루트", "flute"],
    # 템포 보조
    "fast":       ["fast", "빠른", "quick", "rapid", "tempo", "빠르게"],
    "slow":       ["slow", "느린", "느리게", "천천히"],
    "medium":     ["medium", "보통", "중간", "moderate"],
    # 음색
    "warm":       ["warm", "따뜻한", "warm-timbre", "따스한"],
    "cold":       ["cold", "차가운", "icy", "cool"],
    "short":      ["short", "짧은", "brief", "short-clip"],
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

    # CLAP text_for_clap 구성:
    # 1) 무드 동의어에서 영문 위주 최대 12 토큰 (CLAP 77 토큰 한계)
    # 2) query_expand 양방향 확장 (sparse/ASF 채널 + CLAP 크로스링구얼 보조)
    _extra_words: list[str] = []
    _seen_extra: set[str] = set()
    for _m in mood_boosts:
        for _w in MOOD_SYNONYMS.get(_m, []):
            _wl = _w.lower()
            if _wl not in _seen_extra and _wl not in q.lower():
                _extra_words.append(_w)
                _seen_extra.add(_wl)
                if len(_extra_words) >= 12:
                    break
        if len(_extra_words) >= 12:
            break

    # query_expand 양방향 확장 추가 (sparse/ASF 채널용)
    try:
        from services.query_expand import expand_bilingual as _expand
        _expanded_q = _expand(q)
        # 원본 쿼리와 다른 경우에만 extra 에 추가
        if _expanded_q != q:
            _expand_extra = _expanded_q[len(q):].strip()
            if _expand_extra:
                _extra_words.append(_expand_extra)
    except Exception:
        pass

    extra = " ".join(_extra_words)
    text_for_clap = f"{q} {extra}".strip() if extra else q

    return ParsedQuery(
        raw=q,
        artist_hint=artist_hint,
        title_hint=title_hint,
        broad_artist_search=broad,
        text_for_clap=text_for_clap,
        mood_boosts=mood_boosts,
    )
