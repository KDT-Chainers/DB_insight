"""2nd round coverage scan — image captions, BGM moods, music genres, edge cases."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.query_expand import expand_bilingual as eb

pairs = [
    # 이미지 — 색상/질감/조명
    ("빨간색 붉은 색깔",        "red color bright"),
    ("파란색 하늘 파랑",        "blue sky color"),
    ("흰색 흰 밝은",            "white bright light"),
    ("어두운 검은 밤",          "dark black night"),
    ("텍스처 질감 표면",        "texture surface material"),
    # 이미지 — 사물/물건
    ("책상 의자 가구",          "desk chair furniture"),
    ("시계 손목 시간",          "watch clock time"),
    ("안경 렌즈 눈",            "glasses lens eye"),
    ("가방 백 소지품",          "bag backpack handbag"),
    ("휴대폰 스마트폰 화면",    "smartphone phone screen"),
    # BGM 추가 무드/장르
    ("재즈 스윙 블루스",        "jazz swing blues"),
    ("클래식 피아노 바이올린",  "classical piano violin"),
    ("힙합 랩 비트",            "hiphop rap beat"),
    ("팝 케이팝 아이돌",        "pop kpop idol music"),
    ("전자음악 EDM 테크노",     "electronic EDM techno"),
    ("어쿠스틱 통기타 포크",    "acoustic guitar folk"),
    ("긴박한 빠른 격렬한",      "intense fast aggressive"),
    ("평화로운 명상 요가",      "peaceful meditation yoga"),
    # 음악 장르/분위기
    ("트로트 성인 가요",        "trot adult korean music"),
    ("발라드 감성 서정적",      "ballad emotional lyrical"),
    ("인디 밴드 공연",          "indie band live concert"),
    # 영화/드라마 세부
    ("로맨스 사랑 커플",        "romance love couple"),
    ("미스터리 추리 탐정",      "mystery detective thriller"),
    ("SF 공상과학 우주",        "sci-fi science fiction space"),
    ("애니메이션 만화 캐릭터",  "animation cartoon character"),
    # 문서 추가
    ("보고서 분석 통계",        "report analysis statistics"),
    ("계획서 제안 프로젝트",    "plan proposal project"),
    ("논문 연구 학술",          "paper research academic"),
    # 기타 틈새
    ("명절 추석 설날",          "holiday chuseok new year"),
    ("패션 의류 스타일",        "fashion clothing style"),
    ("반려동물 강아지 고양이",  "pet dog cat"),
]

WEAK = []
for ko, en in pairs:
    ko_exp = eb(ko)
    en_exp = eb(en)
    ko_t = set(ko_exp.lower().split())
    en_t = set(en_exp.lower().split())
    shared = ko_t & en_t
    ov = len(shared)
    status = "OK  " if ov >= 2 else "WEAK"
    if status.strip() == "WEAK":
        WEAK.append((ko, en, ov, shared, ko_exp, en_exp))
    print(f"[{status}] ov={ov}  '{ko}' vs '{en}'")

print(f"\nWEAK pairs: {len(WEAK)}/{len(pairs)}")
for ko, en, ov, shared, ko_exp, en_exp in WEAK:
    print(f"  KO: '{ko}' -> {ko_exp[:80]}")
    print(f"  EN: '{en}' -> {en_exp[:80]}")
    print()
