"""한↔영 쿼리 확장 — 의미 동일 다국어 토큰을 검색 쿼리에 추가.

배경:
  BGE-M3 dense 임베딩은 다국어 의미를 잘 포착하지만, sparse 채널과
  ASF token 매칭은 정확한 토큰 일치만 가능 → '어린이' 와 'children' 검색
  결과가 달라짐.

해결:
  검색 시점에 query 를 자동 확장:
    '어린이' → '어린이 children kids child'
    'children' → 'children 어린이 아이들'
  이렇게 하면 sparse + ASF 도 다국어 토큰 모두 커버.

사용:
  from services.query_expand import expand_bilingual
  expanded = expand_bilingual('어린이')  # '어린이 children kids child'
"""
from __future__ import annotations
import re

# 한↔영 양방향 사전 — 데이터셋 도메인 특화 + 일반 명사
# 도메인: 뉴스/방송, 스포츠, 연예/엔터, 정치, 경제/금융, 기술/AI,
#          의료/과학, 사회/생활, 문서/업무, 음악(BGM), 이미지 묘사
_KO_EN: dict[str, list[str]] = {

    # ── 인물 / 사람 ────────────────────────────────────────────────
    "어린이":       ["children", "kids", "child"],
    "아이들":       ["children", "kids"],
    "아이":         ["child", "kid"],
    "사람":         ["person", "people"],
    "인물":         ["person", "portrait"],
    "여성":         ["woman", "female", "women"],
    "남성":         ["man", "male", "men"],
    "학생":         ["student"],
    "선생":         ["teacher"],
    "교사":         ["teacher"],
    "노인":         ["elderly", "senior"],
    "가족":         ["family"],
    "시민":         ["citizen", "public"],
    "국민":         ["citizen", "people", "public"],
    "전문가":       ["expert", "specialist"],
    "의원":         ["lawmaker", "congressman", "politician"],
    "장관":         ["minister", "secretary"],
    "대통령":       ["president"],
    "기자":         ["reporter", "journalist"],
    "앵커":         ["anchor", "newscaster"],
    "아나운서":     ["announcer", "newscaster"],
    "선수":         ["athlete", "player"],
    "감독":         ["director", "coach", "manager"],
    "배우":         ["actor", "actress"],
    "가수":         ["singer", "artist"],
    "연예인":       ["celebrity", "entertainer", "star"],
    "아이돌":       ["idol", "kpop idol"],
    "유튜버":       ["youtuber", "creator", "influencer"],
    "회장":         ["chairman", "president", "CEO"],
    "대표":         ["representative", "CEO", "president"],
    "교수":         ["professor"],
    "의사":         ["doctor", "physician"],
    "변호사":       ["lawyer", "attorney"],
    "검사":         ["prosecutor"],
    "판사":         ["judge"],

    # ── 장소 / 공간 ────────────────────────────────────────────────
    # (바다/산/강/호수는 아래 동물/자연물 섹션에 더 완전한 형태로 정의됨)
    "산맥":         ["mountain range", "mountains"],
    "도시":         ["city", "urban"],
    "건물":         ["building", "structure"],
    "공원":         ["park"],
    "학교":         ["school"],
    "대학":         ["university", "college"],
    "회사":         ["company", "office", "corporation"],
    "사무실":       ["office"],
    "도서관":       ["library"],
    "박물관":       ["museum"],
    "병원":         ["hospital", "clinic"],
    "법원":         ["court", "courthouse"],
    "국회":         ["parliament", "national assembly", "congress"],
    "청와대":       ["blue house", "presidential office"],
    "경찰":         ["police"],
    "검찰":         ["prosecution", "prosecutor's office"],
    "공항":         ["airport"],
    "항구":         ["port", "harbor"],
    "공장":         ["factory", "plant"],
    "식당":         ["restaurant"],
    "가게":         ["store", "shop"],
    "시장":         ["market"],
    "백화점":       ["department store"],
    "아파트":       ["apartment"],
    "지하철":       ["subway", "metro"],
    "버스":         ["bus"],

    # ── 동물 / 자연물 ──────────────────────────────────────────────
    "고양이":       ["cat", "kitten", "feline"],
    "강아지":       ["dog", "puppy", "canine"],
    "개":           ["dog"],
    "새":           ["bird"],
    "물고기":       ["fish"],
    "꽃":           ["flower", "flowers"],
    "나무":         ["tree", "trees"],
    "풀":           ["grass"],
    # 자연 풍경
    "자연":         ["nature", "natural", "outdoor"],
    "풍경":         ["landscape", "scenery", "scene", "view"],
    "경치":         ["scenery", "landscape", "view"],
    "산":           ["mountain", "mountains", "hill"],
    "바다":         ["sea", "ocean", "beach", "coast"],
    "강":           ["river", "stream"],
    "하늘":         ["sky", "heaven"],
    "구름":         ["cloud", "clouds"],
    "숲":           ["forest", "woods", "woodland"],
    "들판":         ["field", "meadow", "plain"],
    "해변":         ["beach", "seashore", "coast"],
    "호수":         ["lake", "pond"],
    "폭포":         ["waterfall", "falls"],
    "노을":         ["sunset", "dusk", "golden hour", "twilight"],
    "일몰":         ["sunset", "dusk", "sundown"],
    "석양":         ["sunset", "dusk", "evening glow"],
    "일출":         ["sunrise", "dawn"],

    # ── 사물 ──────────────────────────────────────────────────────
    "노트북":       ["laptop", "notebook"],
    "컴퓨터":       ["computer", "PC"],
    "스마트폰":     ["smartphone", "phone", "mobile"],
    "자동차":       ["car", "vehicle", "automobile"],
    "운전":         ["driving", "drive"],
    "음식":         ["food", "meal"],
    "옷":           ["clothes", "clothing"],
    "책":           ["book"],
    "문서":         ["document", "paper"],
    "사진":         ["photo", "photograph", "picture"],
    "그림":         ["drawing", "picture", "image"],
    "카메라":       ["camera"],

    # ── 뉴스 / 방송 ────────────────────────────────────────────────
    "뉴스":         ["news", "broadcast"],
    "방송":         ["broadcast", "broadcasting", "media"],
    "라디오":       ["radio", "broadcast"],
    "프로그램":     ["program", "show"],
    "토론":         ["debate", "discussion"],
    "인터뷰":       ["interview"],
    "팟캐스트":     ["podcast"],
    "취재":         ["coverage", "reporting", "investigation"],
    "보도":         ["report", "coverage", "news report"],
    "속보":         ["breaking news"],
    "단독":         ["exclusive", "scoop"],
    "기사":         ["article", "news article", "story"],
    "특보":         ["special report"],
    "논평":         ["commentary", "editorial"],
    "해설":         ["analysis", "commentary", "explanation"],
    "사설":         ["editorial"],
    "여론":         ["public opinion", "opinion poll"],
    "조사":         ["survey", "investigation", "research"],

    # ── 스포츠 ────────────────────────────────────────────────────
    "농구":         ["basketball"],
    "야구":         ["baseball"],
    "축구":         ["soccer", "football"],
    "배구":         ["volleyball"],
    "골프":         ["golf"],
    "수영":         ["swimming"],
    "테니스":       ["tennis"],
    "럭비":         ["rugby"],
    "스키":         ["skiing", "ski"],
    "격투":         ["fighting", "combat sport"],
    "권투":         ["boxing"],
    "씨름":         ["Korean wrestling", "ssireum"],
    "태권도":       ["taekwondo"],
    "올림픽":       ["Olympics", "Olympic"],
    "월드컵":       ["World Cup"],
    "리그":         ["league"],
    "하이라이트":   ["highlight", "highlights"],
    "결승":         ["final", "championship"],
    "득점":         ["score", "goal"],
    "경기":         ["game", "match", "competition"],
    "승리":         ["victory", "win"],
    "패배":         ["defeat", "loss"],
    "선발":         ["starting lineup", "selection"],
    "플레이오프":   ["playoffs"],
    "챔피언":       ["champion", "championship"],
    "국가대표":     ["national team", "national representative"],
    "프로":         ["professional", "pro"],
    # EN single-word → KO expansions (for "soccer national team" tokenized as ["soccer","national","team"])
    "national":     ["국가대표", "국내"],
    "team":         ["팀", "국가대표"],

    # ── 연예 / 엔터테인먼트 ────────────────────────────────────────
    "드라마":       ["drama", "TV show", "series"],
    "영화":         ["movie", "film", "cinema"],
    "예능":         ["variety show", "entertainment show"],
    "시트콤":       ["sitcom"],
    "다큐멘터리":   ["documentary"],
    "콘서트":       ["concert"],
    "공연":         ["performance", "show"],
    "연예대상":     ["entertainment award", "broadcasting award"],
    "시상식":       ["award ceremony", "awards"],
    "음반":         ["album", "record"],
    "데뷔":         ["debut"],
    "기획사":       ["agency", "entertainment company"],
    "소속사":       ["agency", "management company"],
    "팬":           ["fan", "fans"],
    "뮤직비디오":   ["music video", "MV"],
    "코미디":       ["comedy"],
    "로맨스":       ["romance"],
    "액션":         ["action"],
    "스릴러":       ["thriller"],
    "공포":         ["horror"],

    # ── 정치 ──────────────────────────────────────────────────────
    "정치":         ["politics", "political"],
    "정부":         ["government"],
    "선거":         ["election", "vote"],
    "투표":         ["vote", "voting", "ballot"],
    "탄핵":         ["impeachment"],
    "계엄":         ["martial law"],
    "여당":         ["ruling party", "government party"],
    "야당":         ["opposition party"],
    "국정":         ["state affairs", "government affairs"],
    "공천":         ["nomination", "party nomination"],
    "대선":         ["presidential election"],
    "총선":         ["general election"],
    "지선":         ["local election"],
    "헌법":         ["constitution", "constitutional"],
    "법":           ["law", "legal"],
    "법안":         ["bill", "legislation"],
    "개헌":         ["constitutional amendment"],
    "특검":         ["special prosecutor", "special investigation"],
    "검찰개혁":     ["prosecution reform"],
    "청문회":       ["confirmation hearing"],

    # ── 경제 / 금융 ────────────────────────────────────────────────
    "경제":         ["economy", "economic"],
    "금융":         ["finance", "financial"],
    "주식":         ["stock", "stocks", "shares"],
    "증시":         ["stock market", "stock exchange"],
    "코스피":       ["KOSPI", "Korea stock index"],
    "코스닥":       ["KOSDAQ"],
    "부동산":       ["real estate", "property"],
    "아파트값":     ["apartment price", "housing price"],
    "금리":         ["interest rate"],
    "환율":         ["exchange rate", "currency"],
    "물가":         ["price", "inflation", "cost of living"],
    "인플레이션":   ["inflation"],
    "경기침체":     ["recession", "economic downturn"],
    "성장":         ["growth"],
    "GDP":          ["GDP", "gross domestic product"],
    "수출":         ["export", "exports"],
    "수입":         ["import", "imports"],
    "무역":         ["trade"],
    "관세":         ["tariff", "customs"],
    "스타트업":     ["startup"],
    "투자":         ["investment", "invest"],
    "펀드":         ["fund"],
    "채권":         ["bond", "bonds"],
    "가상화폐":     ["cryptocurrency", "crypto", "bitcoin"],
    "비트코인":     ["bitcoin", "cryptocurrency"],
    "은행":         ["bank", "banking"],
    "보험":         ["insurance"],
    "연금":         ["pension"],
    "예산":         ["budget", "fiscal"],
    "세금":         ["tax", "taxes"],
    "복지":         ["welfare", "social welfare"],

    # ── 기술 / AI ──────────────────────────────────────────────────
    "기술":         ["technology", "technical", "tech"],
    "인공지능":     ["AI", "artificial intelligence", "machine learning"],
    "AI":           ["AI", "인공지능", "artificial intelligence"],
    # EN single-word → KO expansions (for "artificial intelligence" query tokenized as ["artificial","intelligence"])
    "artificial":   ["인공지능", "AI"],
    "intelligence": ["인공지능", "AI"],
    "챗봇":         ["chatbot", "AI assistant"],
    "자율주행":     ["autonomous driving", "self-driving"],
    "반도체":       ["semiconductor", "chip"],
    "소프트웨어":   ["software"],
    "하드웨어":     ["hardware"],
    "플랫폼":       ["platform"],
    "클라우드":     ["cloud"],
    "빅데이터":     ["big data"],
    "사이버":       ["cyber"],
    "해킹":         ["hacking", "hack", "cyberattack"],
    "드론":         ["drone"],
    "로봇":         ["robot", "robotics"],
    "전기차":       ["electric vehicle", "EV", "electric car"],
    "배터리":       ["battery"],
    "태양광":       ["solar", "solar energy", "photovoltaic"],
    "신재생":       ["renewable energy", "clean energy"],
    "탄소":         ["carbon"],
    "디지털":       ["digital"],
    "온라인":       ["online"],
    "메타버스":     ["metaverse"],
    "데이터":       ["data"],
    "데이터센터":   ["data center", "datacenter"],
    "정보":         ["information"],
    "보안":         ["security", "cybersecurity"],
    "앱":           ["app", "application"],

    # ── 의료 / 과학 / 건강 ─────────────────────────────────────────
    "의료":         ["medical", "healthcare", "medicine"],
    "건강":         ["health", "healthy"],
    "질병":         ["disease", "illness"],
    "코로나":       ["COVID", "coronavirus", "pandemic"],
    "백신":         ["vaccine", "vaccination"],
    "암":           ["cancer"],
    "수술":         ["surgery", "operation"],
    "치료":         ["treatment", "therapy", "cure"],
    "약":           ["medicine", "drug", "medication"],
    "과학":         ["science", "scientific"],
    "연구":         ["research", "study"],
    "실험":         ["experiment", "test"],
    "우주":         ["space", "universe", "cosmos"],
    "환경":         ["environment", "environmental"],
    "기후":         ["climate"],
    "지진":         ["earthquake"],
    "홍수":         ["flood"],

    # ── 사회 / 생활 ────────────────────────────────────────────────
    "사회":         ["society", "social"],
    "문화":         ["culture", "cultural"],
    "역사":         ["history", "historical"],
    "교육":         ["education", "educational"],
    "취업":         ["employment", "employ", "job", "career"],
    "취준":         ["job seeking", "job hunting"],
    "이민":         ["immigration", "immigrant"],
    "저출생":       ["low birth rate", "declining birth rate"],
    "고령화":       ["aging society", "aging population"],
    "청년":         ["youth", "young people"],
    "노동":         ["labor", "work"],
    "임금":         ["wage", "salary"],
    "파업":         ["strike"],
    "범죄":         ["crime", "criminal"],
    "사고":         ["accident", "incident"],
    "화재":         ["fire"],
    "교통":         ["traffic", "transportation"],
    "부패":         ["corruption"],
    "인권":         ["human rights"],

    # ── 국제 / 외교 ────────────────────────────────────────────────
    "미국":         ["US", "USA", "United States", "America", "American"],
    "중국":         ["China", "Chinese"],
    "일본":         ["Japan", "Japanese"],
    "북한":         ["North Korea", "DPRK"],
    "러시아":       ["Russia", "Russian"],
    "유럽":         ["Europe", "European"],
    "외교":         ["diplomacy", "diplomatic"],
    "정상회담":     ["summit", "summit meeting"],
    "군사":         ["military"],
    "전쟁":         ["war", "warfare"],
    "평화":         ["peace"],
    "제재":         ["sanctions"],
    "트럼프":       ["Trump"],
    "바이든":       ["Biden"],

    # ── 업무 / 문서 ────────────────────────────────────────────────
    "회의":         ["meeting", "conference"],
    "발표":         ["presentation", "report", "announcement"],
    "강의":         ["lecture", "lesson"],
    "분석":         ["analysis", "analytical"],
    "운영":         ["operation"],
    "관리":         ["management", "manage"],
    "개발":         ["development", "develop"],
    "지원":         ["support"],
    "보고서":       ["report", "white paper"],
    "연간보고서":   ["annual report", "yearly report"],
    "실태조사":     ["survey", "survey report", "investigation report"],
    "통계":         ["statistics", "statistical"],
    "정책":         ["policy", "policies"],
    "산업":         ["industry", "industrial"],
    "기업":         ["company", "enterprise", "corporation"],
    "서비스":       ["service"],
    "이력서":       ["resume", "CV", "curriculum vitae"],
    "채용":         ["recruitment", "hiring", "job opening"],
    "계약":         ["contract", "agreement"],
    "합의":         ["agreement", "consensus"],
    "규정":         ["regulation", "rule"],
    "지침":         ["guideline", "directive"],
    "기준":         ["standard", "criteria"],
    "허가":         ["permit", "approval", "license"],
    "신고":         ["report", "declaration", "filing"],
    "감사":         ["audit", "inspection"],
    "주민등록증":   ["resident registration", "id card", "ID"],
    "운전면허증":   ["driver license", "driver's license"],
    "신분증":       ["id card", "ID", "identification"],
    "여권":         ["passport"],

    # ── 장소/지역 보조 ─────────────────────────────────────────────
    "지하":         ["basement", "underground", "subway"],
    "텍스트":       ["text"],
    "캡션":         ["caption"],

    # ── 색상 ──────────────────────────────────────────────────────
    "빨간":         ["red"],
    "파란":         ["blue"],
    "노란":         ["yellow"],
    "초록":         ["green"],
    "흰":           ["white"],
    "검은":         ["black"],

    # ── 음악 / BGM ────────────────────────────────────────────────
    "음악":         ["music"],
    "노래":         ["song"],
    "피아노":       ["piano"],
    "기타":         ["guitar"],
    "드럼":         ["drum", "drums"],
    "오케스트라":   ["orchestra", "orchestral"],
    "발라드":       ["ballad"],
    "댄스":         ["dance"],
    "록":           ["rock"],
    "재즈":         ["jazz"],
    "클래식":       ["classical"],
    "전자":         ["electronic"],
    "악기":         ["instrument", "instrumental"],
    "보컬":         ["vocal", "vocals"],
    "분위기":       ["mood", "vibe", "atmosphere"],
    "잔잔한":       ["calm", "peaceful", "soothing", "mellow"],
    "신나는":       ["upbeat", "energetic", "lively", "exciting"],
    "조용한":       ["quiet", "silent", "soft", "gentle"],
    "밝은":         ["bright", "cheerful", "happy", "positive"],
    "어두운":       ["dark", "gloomy", "somber", "dim"],
    "빠른":         ["fast", "upbeat", "energetic", "driving"],
    "느린":         ["slow", "calm", "relaxed", "laid-back"],
    "감성":         ["emotional", "sentimental", "atmospheric"],
    # BGM mood & tension terms
    "긴장":         ["tense", "tension", "suspenseful", "dramatic"],
    "긴장감":       ["tension", "tense", "suspense", "dramatic intensity"],
    "드라마틱":     ["dramatic", "cinematic", "epic"],
    "웅장한":       ["epic", "grand", "majestic", "orchestral"],
    "슬픈":         ["sad", "melancholic", "sorrowful", "melancholy"],
    "우울한":       ["sad", "melancholic", "depressing", "gloomy"],
    "활기찬":       ["lively", "vibrant", "energetic", "vivid"],
    "경쾌한":       ["cheerful", "light", "bouncy", "lively"],
    "로맨틱":       ["romantic", "love", "tender", "intimate"],
    "신비로운":     ["mysterious", "mystical", "ethereal", "ambient"],
    "편안한":       ["relaxing", "comfortable", "cozy", "soothing"],
    "몽환적":       ["dreamy", "ethereal", "hazy", "ambient"],
    "강렬한":       ["intense", "powerful", "strong", "forceful"],
    "부드러운":     ["smooth", "soft", "gentle", "mellow"],
    "따뜻한":       ["warm", "cozy", "heartwarming", "gentle"],
    "차가운":       ["cold", "cool", "icy", "stark"],
    "힙합":         ["hip hop", "rap"],
    "팝":           ["pop"],
    "R&B":          ["R&B", "rhythm and blues"],
    "트로트":       ["trot", "Korean trot"],
    "국악":         ["Korean traditional music", "gugak"],
    "OST":          ["OST", "soundtrack", "original soundtrack"],
    "배경음악":     ["background music", "BGM"],
    "반주":         ["accompaniment", "background music"],

    # ── 악기 / 음악 상세 ──────────────────────────────────────────────
    "첼로":         ["cello"],
    "바이올린":     ["violin"],
    "플루트":       ["flute"],
    "색소폰":       ["saxophone", "sax"],
    "트럼펫":       ["trumpet"],
    "베이스기타":   ["bass guitar", "bass"],
    "신디사이저":   ["synthesizer", "synth"],
    "전자기타":     ["electric guitar"],
    "어쿠스틱":     ["acoustic"],
    "현악기":       ["strings", "string instrument"],
    "관악기":       ["wind instrument", "brass", "woodwind"],
    "타악기":       ["percussion", "drums"],
    "앙상블":       ["ensemble"],
    "협주곡":       ["concerto"],
    "교향곡":       ["symphony"],
    "멜로디":       ["melody"],
    "화음":         ["harmony", "chord"],
    "박자":         ["rhythm", "tempo", "beat"],
    "비트":         ["beat", "rhythm", "groove"],
    "전주":         ["intro", "introduction", "prelude"],
    "후렴":         ["chorus", "refrain"],
    "간주":         ["interlude", "bridge"],

    # ── 영화 / 드라마 상세 ────────────────────────────────────────────
    "출연":         ["starring", "appearance", "cast", "featured"],
    "주연":         ["lead actor", "starring", "leading role"],
    "조연":         ["supporting actor", "co-star"],
    "제목":         ["title"],
    "개봉":         ["release", "premiere", "opening"],
    "상영":         ["screening", "showing"],
    "예고편":       ["trailer", "preview"],
    "결말":         ["ending", "finale", "conclusion"],
    "줄거리":       ["plot", "synopsis", "storyline"],
    "장르":         ["genre"],
    "감동":         ["touching", "moving", "emotional", "heartwarming"],
    "명장면":       ["best scene", "iconic scene", "highlight scene"],

    # ── 스포츠 상세 ───────────────────────────────────────────────────
    "스타":         ["star", "celebrity"],
    "팀":           ["team", "squad"],
    "심판":         ["referee", "judge", "umpire"],
    "코치":         ["coach", "trainer"],
    "공격":         ["attack", "offense", "offensive"],
    "수비":         ["defense", "defensive"],
    "골":           ["goal"],
    "점수":         ["score", "point", "points"],
    "우승":         ["championship", "win", "victory", "title"],
    "준우승":       ["runner-up", "second place"],
    "기록":         ["record"],

    # ── 영상 / 방송 고유명사 ─────────────────────────────────────
    "유퀴즈":       ["You Quiz", "variety show"],
    "다스뵈이다":   ["Das Boot", "political podcast"],
    "뉴스하이킥":   ["News High Kick", "news show"],
    "연예대상":     ["entertainment awards", "MBC awards"],
    "오뚝이":       ["comeback", "resilience"],
    "MBC":          ["MBC", "Munhwa Broadcasting"],
    "KBS":          ["KBS", "Korea Broadcasting"],
    "SBS":          ["SBS"],
    "JTBC":         ["JTBC"],
    "MBN":          ["MBN"],

    # ── 과학 / 학문 ─────────────────────────────────────────────────
    "물리":         ["physics", "physical"],
    "물리학":       ["physics", "physics science"],
    "양자":         ["quantum"],
    "양자역학":     ["quantum mechanics", "quantum physics"],
    "화학":         ["chemistry", "chemical"],
    "생물":         ["biology", "biological"],
    "천문":         ["astronomy", "astronomical"],
    "수학":         ["mathematics", "math"],
    "우주":         ["space", "universe", "cosmos", "cosmic"],
    "진화":         ["evolution", "evolutionary"],
    "상대성이론":   ["relativity", "theory of relativity"],
    "중력":         ["gravity", "gravitation"],
    "의학":         ["medicine", "medical"],

    # ── 교육 / 상담 ──────────────────────────────────────────────────
    "상담":         ["counseling", "consultation", "counselling"],
    "면담":         ["interview", "consultation meeting", "counseling session"],
    "선생님":       ["teacher", "instructor"],
    "교사":         ["teacher", "educator"],
    "학생":         ["student", "pupil"],
    "교육":         ["education", "educational"],
    "수업":         ["class", "lesson", "lecture"],
    "학교":         ["school"],
    "대학":         ["university", "college"],

    # ── 창업 / 사업 ──────────────────────────────────────────────────
    "창업":         ["startup", "entrepreneurship", "founding", "start-up"],
    "사업":         ["business", "enterprise"],
    "투자자":       ["investor"],
    "벤처":         ["venture", "startup"],
    "실리콘밸리":   ["Silicon Valley"],

    # ── 시상 / 행사 ──────────────────────────────────────────────────
    "시상":         ["award", "ceremony", "awarding"],
    "시상식":       ["award ceremony", "awards", "awards show", "ceremony"],
    "수상":         ["award winning", "winning award", "receiving award"],
    "대상":         ["grand prize", "top award", "main award"],
    "연예":         ["entertainment", "celebrity"],

    # ── 분위기 / 형용사 ────────────────────────────────────────────
    "최신":         ["latest", "recent", "new"],
    "최고":         ["best", "top", "greatest"],
    "인기":         ["popular", "trending"],
    "화제":         ["trending", "hot topic", "buzz"],
    "논란":         ["controversy", "controversy", "issue"],
    "충격":         ["shock", "shocking"],
    "단독":         ["exclusive"],
    "긴급":         ["urgent", "emergency", "breaking"],
}

# 영 → 한 역방향 lookup (자동 생성)
_EN_KO: dict[str, list[str]] = {}
for _ko, _ens in _KO_EN.items():
    for _en in _ens:
        _EN_KO.setdefault(_en.lower(), []).append(_ko)


from functools import lru_cache


@lru_cache(maxsize=4096)
def expand_bilingual(query: str, max_extra: int = 10) -> str:
    """쿼리를 한↔영 양방향 사전으로 확장.

    예:
      '어린이' → '어린이 children kids child'
      'cat' → 'cat 고양이'
      '취업 통계' → '취업 통계 employment statistics employ statistical'
      '산 풍경' (사전 미등록) → '산 풍경 mountain' (산만 매핑)
      '농구 하이라이트' → '농구 하이라이트 basketball highlight highlights'
      'economy news' → 'economy news 경제 뉴스 financial broadcast'

    Args:
      query: 원본 쿼리
      max_extra: 추가할 토큰 최대 수 (너무 많으면 sparse 노이즈)
                 default 10 (이전 8에서 증가 — 어휘 확장으로 커버리지 향상)
    """
    if not query or not query.strip():
        return query

    # 토큰 추출 — 한글/영문/숫자/대소문자 조합
    tokens = re.findall(r"[가-힣]+|[A-Za-z][A-Za-z0-9&/]*|[0-9]+", query)
    if not tokens:
        return query

    extras: list[str] = []
    seen: set[str] = {t.lower() for t in tokens}

    # 토큰별 최대 추가 수 제한 (per-token cap) — 단일 토큰이 max_extra 를 독점하지 않도록
    per_token_cap = max(2, max_extra // max(len(tokens), 1))

    for t in tokens:
        added_this_token = 0
        # 한 → 영
        for en in _KO_EN.get(t, []):
            el = en.lower()
            if el not in seen:
                extras.append(en)
                seen.add(el)
                added_this_token += 1
                if added_this_token >= per_token_cap:
                    break
        # 영 → 한
        for ko in _EN_KO.get(t.lower(), []):
            if ko not in seen:
                extras.append(ko)
                seen.add(ko)
                added_this_token += 1
                if added_this_token >= per_token_cap:
                    break

    # 전체 상한 준수
    extras = extras[:max_extra]

    if not extras:
        return query
    return f"{query} {' '.join(extras)}"
