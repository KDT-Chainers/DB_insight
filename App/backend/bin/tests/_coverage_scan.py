"""Deep vocabulary coverage scan — identify missing KO↔EN bridges."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.query_expand import expand_bilingual as eb

pairs = [
    # 음식/요리
    ("음식 요리 레시피",        "food cooking recipe"),
    ("김치 한식 전통음식",       "kimchi korean food traditional"),
    ("커피 카페 음료",          "coffee cafe drink beverage"),
    # 여행/관광
    ("여행 관광 여행지",        "travel tourism destination"),
    ("호텔 숙박 리조트",        "hotel accommodation resort"),
    ("항공 비행기 공항",        "flight airplane airport"),
    # 스포츠 추가
    ("수영 수영장 선수",        "swimming pool athlete"),
    ("테니스 골프 스포츠",      "tennis golf sports"),
    ("마라톤 달리기 육상",      "marathon running athletics"),
    # 기술/IT 추가
    ("반도체 칩 제조",          "semiconductor chip manufacturing"),
    ("배터리 전기차 충전",      "battery electric vehicle charging"),
    ("클라우드 서버 데이터",    "cloud server data"),
    ("해킹 보안 사이버",        "hacking security cyber"),
    # 환경/자연
    ("미세먼지 대기 오염",      "fine dust air pollution"),
    ("산불 가뭄 기후",          "wildfire drought climate"),
    ("재활용 쓰레기 분리수거",  "recycling waste sorting"),
    # 사회/문화 추가
    ("노숙자 빈곤 복지",        "homeless poverty welfare"),
    ("장애인 복지 지원",        "disabled welfare support"),
    ("종교 불교 기독교",        "religion buddhism christianity"),
    ("출산율 저출생 인구",      "birth rate population decline"),
    # 경제 추가
    ("물가 인플레이션 경기",    "inflation economy recession"),
    ("수출 무역 관세",          "export trade tariff"),
    ("실업률 고용 경제",        "unemployment employment economy"),
    # 국제
    ("북한 핵 미사일",          "north korea nuclear missile"),
    ("전쟁 분쟁 군사",          "war conflict military"),
    ("외교 정상회담 협력",      "diplomacy summit cooperation"),
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
        WEAK.append((ko, en, ov, shared))
    print(f"[{status}] ov={ov}  '{ko}' vs '{en}'")
    if ov < 2:
        print(f"         shared={shared}")

print(f"\nWEAK pairs: {len(WEAK)}/{len(pairs)}")
for ko, en, ov, shared in WEAK:
    ko_exp2 = eb(ko)
    en_exp2 = eb(en)
    print(f"  '{ko}' -> {ko_exp2[:70]}")
    print(f"  '{en}' -> {en_exp2[:70]}")
    print()
