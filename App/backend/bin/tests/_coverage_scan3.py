"""3rd coverage scan — weather, objects, BGM instruments, medical details, tech."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.query_expand import expand_bilingual as eb

pairs = [
    # 날씨 / 기상
    ("비 비오는 날",            "rain rainy weather"),
    ("눈 눈오는 겨울",          "snow snowy winter"),
    ("바람 강풍 폭풍",          "wind storm gale"),
    ("맑음 맑은 하늘",          "clear sunny sky"),
    ("구름 흐린 날",            "cloud cloudy overcast"),
    ("무지개 색깔 하늘",        "rainbow color sky"),
    # 이미지 — 객체/사물
    ("신발 운동화 구두",        "shoes sneakers footwear"),
    ("모자 헬멧 머리",          "hat helmet headwear"),
    ("음료 물병 컵",            "drink bottle cup"),
    ("조명 불빛 전등",          "light lamp illumination"),
    ("다리 교각 강",            "bridge river structure"),
    ("지하철 기차 철도",        "subway train railway"),
    # BGM 악기/템포
    ("바이올린 현악 선율",      "violin strings melody"),
    ("드럼 타악 비트",          "drums percussion beat"),
    ("트럼펫 관악 브라스",      "trumpet brass wind instrument"),
    ("신디사이저 전자음 EDM",   "synthesizer electronic EDM"),
    ("느린 템포 조용한",        "slow tempo quiet relaxing"),
    ("빠른 템포 에너지",        "fast tempo energy upbeat"),
    # 의료 상세
    ("암 종양 항암",            "cancer tumor chemotherapy"),
    ("심장 심박 혈압",          "heart rate blood pressure cardiac"),
    ("뇌 신경 뇌졸중",          "brain nerve stroke"),
    ("피부 피부과 알레르기",    "skin dermatology allergy"),
    # 기술 상세
    ("배터리 충전 전력",        "battery charging power"),
    ("드론 무인기 항공",        "drone UAV aerial"),
    ("로봇 자동화 기계",        "robot automation machine"),
    ("가상현실 VR AR",          "virtual reality VR augmented"),
    # 문화/라이프스타일
    ("독서 책 도서관",          "reading book library"),
    ("요가 명상 스트레칭",      "yoga meditation stretching"),
    ("등산 트레킹 하이킹",      "hiking trekking mountain trail"),
    ("낚시 바다 강",            "fishing sea river angling"),
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
