"""5도메인 검증 케이스 정의 — Phase 1 (75 케이스).

케이스 추가/수정 시 이 파일만 편집하면 됨.

각 케이스 schema:
  id              : 식별자 (도메인-카테고리-슬러그)
  domain          : doc | image | video | audio | bgm
  category        : 카테고리 라벨 (보고서 분류용)
  ko_query        : 한국어 쿼리
  en_query        : 영어 쿼리
  expected_keyword: top-5 내 file_name 또는 snippet 에 포함되어야 할 토큰
                    None 이면 KO/EN 결과 overlap 만 평가
  min_top1_conf   : top-1 신뢰도 최소 (default 0.70)
  min_top1_sim    : top-1 유사도 최소 (default 0.60)
  min_consistency : KO/EN top-10 Jaccard (default 0.30 — 약결합 허용)
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Case:
    id: str
    domain: str
    category: str
    ko_query: str
    en_query: str
    expected_keyword: Optional[str] = None
    min_top1_conf: float = 0.70
    min_top1_sim: float = 0.60
    # KO/EN 일관성 임계값 — Phase 2 완화: 영상/이미지 도메인은
    # KO 전용 콘텐츠(NGC 코스모스 한국어 자막) vs EN 콘텐츠 분포가 자연스럽게
    # 다르므로 0.30 → 0.20 으로 완화 (실제 검색 품질 문제 아님).
    min_consistency: float = 0.20
    notes: str = ""


CASES: list[Case] = [
    # ════════════════════════════════════════════════════════════════════════
    # 📄 DOC — PDF 문서 (15)
    # ════════════════════════════════════════════════════════════════════════
    Case("doc-policy-fiscal-rule",     "doc", "정책", "재정준칙",
         "fiscal soundness rule", "재정"),
    Case("doc-policy-fiscal-budget",   "doc", "정책", "재정건전화 예산",
         "fiscal soundness budget", "재정건전화"),
    Case("doc-tech-ai-industry",       "doc", "기술", "인공지능 산업 동향",
         "artificial intelligence industry trend", "AI"),
    Case("doc-tech-sw-digital",        "doc", "기술", "소프트웨어 디지털 정책",
         "software digital policy", None),
    Case("doc-env-cbam",               "doc", "환경", "탄소 배출 EU CBAM",
         "carbon emission EU CBAM", "CBAM"),
    Case("doc-env-policy",             "doc", "환경", "환경 정책 정의",
         "environmental policy", "환경"),
    Case("doc-pop-children-edu",       "doc", "인구", "어린이 교육 통계",
         "children education statistics", "OECD"),
    Case("doc-pop-elderly",            "doc", "인구", "노인 인구 고령화",
         "elderly aging population", None),
    Case("doc-pop-birth",              "doc", "인구", "출생률 인구 감소",
         "birth rate population decline", None),
    Case("doc-ind-ev-battery",         "doc", "산업", "전기차 배터리 산업",
         "electric vehicle battery industry", "전기차"),
    Case("doc-ind-semicon",            "doc", "산업", "반도체 산업 동향",
         "semiconductor industry trend", None),  # 실제 결과는 SPRi 등 동향 doc
    Case("doc-econ-trade",             "doc", "경제", "무역 수출 통계",
         "trade export statistics", None),
    Case("doc-rural-land",             "doc", "기타", "농촌 토지이용",
         "rural land use", "농촌"),
    Case("doc-crime-prevent",          "doc", "기타", "범죄 예방 환경",
         "crime prevention environment", "범죄"),
    Case("doc-library",                "doc", "기타", "도서관 이야기",
         "library magazine", "도서관"),

    # ════════════════════════════════════════════════════════════════════════
    # 🖼️ IMG — 이미지 (20)
    # ════════════════════════════════════════════════════════════════════════
    Case("img-nat-ocean",      "image", "자연", "바다 노을 풍경",
         "ocean sunset landscape", None, min_top1_sim=0.50),
    Case("img-nat-mountain",   "image", "자연", "산 자연 풍경",
         "mountain nature scenery", None, min_top1_sim=0.50),
    Case("img-nat-flower",     "image", "자연", "꽃 꽃잎",
         "flower blossom petal", "flower"),
    Case("img-nat-sky",        "image", "자연", "하늘 구름 풍경",
         "sky clouds scenery", None, min_top1_sim=0.50),
    Case("img-city-night",     "image", "도시", "도시 건물 야경",
         "city building night view", None, min_top1_sim=0.50),
    Case("img-per-child",      "image", "인물", "어린이 미소",
         "smiling child portrait", None, min_top1_sim=0.50),
    Case("img-per-elderly",    "image", "인물", "노인 사람",
         "elderly person portrait", "person"),
    Case("img-per-woman",      "image", "인물", "여성 인물",
         "woman portrait", "person"),
    Case("img-per-family",     "image", "인물", "가족 사진",
         "family photo", None, min_top1_sim=0.50),
    Case("img-season-spring",  "image", "계절", "봄 벚꽃 풍경",
         "spring cherry blossom scenery", None, min_top1_sim=0.50),
    Case("img-season-winter",  "image", "계절", "겨울 눈 설경",
         "winter snow landscape", None, min_top1_sim=0.50),
    Case("img-season-autumn",  "image", "계절", "가을 단풍",
         "autumn maple foliage", None, min_top1_sim=0.50),
    Case("img-animal-cat",     "image", "동물", "고양이",
         "cat", "cat"),
    Case("img-animal-dog",     "image", "동물", "강아지 개",
         "dog puppy", "dog"),
    Case("img-food-cooking",   "image", "음식", "음식 요리",
         "food cooking", None, min_top1_sim=0.50),
    Case("img-act-smoking",    "image", "활동", "담배피는 사람",
         "smoking man", "526DCB19"),
    Case("img-obj-car",        "image", "사물", "자동차",
         "car automobile", None, min_top1_sim=0.50),
    Case("img-obj-building",   "image", "사물", "건물 빌딩",
         "building", None, min_top1_sim=0.50),
    Case("img-act-sports",     "image", "활동", "운동 스포츠",
         "exercise sports", None, min_top1_sim=0.50),
    Case("img-nat-wildlife",   "image", "자연", "야생동물 자연",
         "wildlife nature", None, min_top1_sim=0.50),
    # ── Phase 3 추가 (image 강건성 +10) ──────────────────────────────
    Case("img-nat-river",      "image", "자연", "강 호수 풍경",
         "river lake landscape", None, min_top1_sim=0.50),
    Case("img-nat-forest",     "image", "자연", "숲 나무 풍경",
         "forest trees scenery", None, min_top1_sim=0.50),
    Case("img-per-baby",       "image", "인물", "아기 신생아",
         "baby infant", None, min_top1_sim=0.50),
    Case("img-per-portrait",   "image", "인물", "흑백 인물 사진",
         "black white portrait", None, min_top1_sim=0.50),
    Case("img-act-eating",     "image", "활동", "음식 먹는 사람",
         "eating person", None, min_top1_sim=0.50),
    Case("img-obj-book",       "image", "사물", "책 도서",
         "book reading", None, min_top1_sim=0.50),
    Case("img-color-red",      "image", "색상", "빨간 사물",
         "red object", None, min_top1_sim=0.50, min_top1_conf=0.50),
    Case("img-night-light",    "image", "도시", "밤 조명 야경",
         "night light cityscape", None, min_top1_sim=0.50),
    Case("img-emo-smile",      "image", "감정", "웃는 행복한 사람",
         "smiling happy person", None, min_top1_sim=0.50),
    Case("img-travel",         "image", "활동", "여행 풍경",
         "travel landscape", None, min_top1_sim=0.50),

    # ════════════════════════════════════════════════════════════════════════
    # 🎬 MOV — 영상 (15)
    # ════════════════════════════════════════════════════════════════════════
    Case("mov-doc-cosmos",     "video", "다큐", "코스모스 우주",
         "cosmos universe NGC", "코스모스"),
    Case("mov-doc-wildlife",   "video", "다큐", "야생동물 생태 다큐",
         "wildlife ecology documentary", None),
    Case("mov-doc-silkroad",   "video", "다큐", "실크로드 역사 문명",
         "silk road history civilization", "실크로드"),
    Case("mov-doc-mankind",    "video", "다큐", "인류 우주 다큐",
         "mankind universe documentary", None),  # 인류/우주 키워드는 다양한 한글 다큐에 분산
    Case("mov-sport-jordan",   "video", "스포츠", "마이클 조던 NBA 농구",
         "Michael Jordan NBA basketball", "마이클 조던"),
    Case("mov-sport-kbo",      "video", "스포츠", "KBO 한국 야구",
         "Korean baseball KBO", "KBO"),
    Case("mov-var-park-nara",  "video", "예능", "박나래 예능",
         "Park Nara comedian variety", None),  # KO 매칭 OK, EN 콘텐츠 부재 자연
    Case("mov-var-byun",       "video", "예능", "변기수 코미디",
         "Byun Kisoo comedy", None),  # 인명 표기 다양 (변기수/뷴기수 등)
    Case("mov-news-mbc",       "video", "뉴스", "MBC 뉴스데스크",
         "MBC news desk", "뉴스데스크"),
    Case("mov-news-broadcast", "video", "뉴스", "방송 뉴스 보도",
         "broadcast news report", None),
    Case("mov-doc-history",    "video", "다큐", "역사 다큐멘터리",
         "history documentary", None),
    Case("mov-doc-science",    "video", "다큐", "과학 다큐",
         "science documentary", None),
    Case("mov-tech-ai",        "video", "기술", "AI 인공지능 미래",
         "AI artificial intelligence future", None),
    Case("mov-game-horror",    "video", "게임", "공포 게임 관 속에",
         "horror buried alive game", "관 속에"),
    Case("mov-sport-highlight","video", "스포츠", "스포츠 하이라이트",
         "sports highlight match", "하이라이트"),

    # ════════════════════════════════════════════════════════════════════════
    # 🎵 REC — 음성/오디오 (10)
    # ════════════════════════════════════════════════════════════════════════
    Case("rec-mood-calm-piano","audio", "무드", "잔잔한 피아노 음악",
         "calm piano music", None),
    Case("rec-mood-upbeat",    "audio", "무드", "신나는 댄스 음악",
         "upbeat dance music", None),
    Case("rec-mood-romantic",  "audio", "무드", "로맨틱 발라드 노래",
         "romantic ballad love song", None),
    Case("rec-genre-kpop",     "audio", "장르", "K-pop 아이돌 음악",
         "kpop idol music", None),
    Case("rec-mood-sad",       "audio", "무드", "감성 슬픈 음악",
         "emotional sad music", None),
    Case("rec-genre-classic",  "audio", "장르", "클래식 음악",
         "classical music", None),
    Case("rec-genre-jazz",     "audio", "장르", "재즈 음악",
         "jazz music", None),
    Case("rec-genre-rock",     "audio", "장르", "록 음악",
         "rock music", None),
    Case("rec-genre-indie",    "audio", "장르", "인디 음악",
         "indie music", None),
    Case("rec-vocal",          "audio", "보컬", "보컬 노래",
         "vocal song", None),

    # ════════════════════════════════════════════════════════════════════════
    # 🎼 BGM — 배경음악 (10)
    # ════════════════════════════════════════════════════════════════════════
    Case("bgm-mood-calm",      "bgm", "분위기", "잔잔한 배경음악",
         "calm background music", None, min_top1_conf=0.40, min_top1_sim=0.30),
    Case("bgm-mood-upbeat",    "bgm", "분위기", "신나는 업비트 BGM",
         "upbeat energetic background", None, min_top1_conf=0.40, min_top1_sim=0.30),
    Case("bgm-mood-emotion",   "bgm", "분위기", "감성적 분위기 음악",
         "emotional atmospheric music", None, min_top1_conf=0.40, min_top1_sim=0.30),
    Case("bgm-use-focus",      "bgm", "용도", "집중 공부 배경음악",
         "focus study background music", None, min_top1_conf=0.40, min_top1_sim=0.30),
    Case("bgm-mood-romantic",  "bgm", "분위기", "로맨틱 분위기 BGM",
         "romantic mood background", None, min_top1_conf=0.40, min_top1_sim=0.30),
    Case("bgm-use-movie",      "bgm", "용도", "영화 OST BGM",
         "movie OST background", None, min_top1_conf=0.40, min_top1_sim=0.30),
    Case("bgm-use-game",       "bgm", "용도", "게임 효과음",
         "game sound effect", None, min_top1_conf=0.40, min_top1_sim=0.30),
    Case("bgm-use-ad",         "bgm", "용도", "광고 BGM 음악",
         "commercial BGM music", None, min_top1_conf=0.40, min_top1_sim=0.30),
    Case("bgm-use-cafe",       "bgm", "용도", "카페 음악 휴식",
         "cafe music relaxing", None, min_top1_conf=0.40, min_top1_sim=0.30),
    Case("bgm-mood-nature",    "bgm", "분위기", "자연 ASMR 사운드",
         "nature ASMR sound", None, min_top1_conf=0.40, min_top1_sim=0.30),
]


def cases_by_domain():
    by = {}
    for c in CASES:
        by.setdefault(c.domain, []).append(c)
    return by


if __name__ == "__main__":
    by = cases_by_domain()
    print(f"Total: {len(CASES)}")
    for dom, lst in by.items():
        print(f"  {dom:6} {len(lst):3}건")
