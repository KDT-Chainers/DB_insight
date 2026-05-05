"""4th coverage scan — niche topics, compound words, cross-domain edge cases."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.query_expand import expand_bilingual as eb

pairs = [
    # 인터넷/SNS
    ("인스타그램 SNS 소셜",     "instagram social media platform"),
    ("트위터 X 트윗",           "twitter tweet social"),
    ("블로그 포스팅 콘텐츠",    "blog post content creator"),
    ("스트리밍 넷플릭스 OTT",   "streaming netflix OTT service"),
    # 부동산/건설
    ("아파트 전세 월세",        "apartment lease rent housing"),
    ("건설 공사 시공",          "construction building site"),
    ("인테리어 디자인 리모델링", "interior design renovation remodeling"),
    # 음식 상세
    ("치킨 삼겹살 고기",        "chicken pork meat grill"),
    ("케이크 디저트 베이킹",    "cake dessert baking pastry"),
    ("술 맥주 와인",            "alcohol beer wine drink"),
    # 자연/동물
    ("강아지 반려견 애완동물",  "dog pet puppy companion"),
    ("고양이 반려묘 애완동물",  "cat pet feline companion"),
    ("새 조류 새소리",          "bird avian birdsong"),
    ("물고기 수족관 해양",      "fish aquarium marine"),
    # 건강/생활
    ("다이어트 운동 체중",      "diet exercise weight loss"),
    ("수면 잠 불면증",          "sleep insomnia rest"),
    ("스트레스 번아웃 휴식",    "stress burnout rest recovery"),
    # 경제 심화
    ("주식 코스피 시장",        "stock KOSPI market"),
    ("암호화폐 비트코인 투자",  "cryptocurrency bitcoin investment"),
    ("부채 대출 금융",          "debt loan finance"),
    # 교육 심화
    ("대학교 입시 수능",        "university entrance exam college"),
    ("온라인 강의 이러닝",      "online learning e-learning lecture"),
    ("졸업 학위 석사",          "graduation degree master"),
    # 에너지/환경
    ("태양광 풍력 신재생",      "solar wind renewable energy"),
    ("핵에너지 원전 방사능",    "nuclear energy power plant radiation"),
    ("전기차 충전 탄소",        "electric car charging carbon"),
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
