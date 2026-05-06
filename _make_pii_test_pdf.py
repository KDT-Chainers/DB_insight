"""SecurityCritic 테스트용 PII 포함 PDF 생성."""
import fitz  # PyMuPDF
from pathlib import Path

OUT = Path(r"C:\Honey\DB_insight\Data\raw_DB\Doc\회의록_PII테스트.pdf")
OUT.parent.mkdir(parents=True, exist_ok=True)

doc = fitz.open()
page = doc.new_page(width=595, height=842)  # A4

# 한글 폰트 등록 (맑은 고딕)
font_path = r"C:\Windows\Fonts\malgun.ttf"
page.insert_font(fontname="malgun", fontfile=font_path)

# 본문 라인
title = "회의록 — 2026년 5월 6일 (PII 차단 테스트용)"
lines = [
    "■ 회의 안건: 신규 직원 등록 및 결제 카드 발급",
    "",
    "■ 참석자 명단",
    "  - 김철수 부장 (주민번호: 820701-1234567)",
    "  - 이영희 과장 (여권번호: M12345678)",
    "  - 박민수 대리 (운전면허: 12-34-567890-12)",
    "",
    "■ 회사 정보",
    "  - 사업자등록번호: 123-45-67890",
    "  - 법인명: (주)테스트컴퍼니",
    "",
    "■ 결제 수단 등록",
    "  - 법인 신용카드 번호: 4111-1111-1111-1111",
    "  - 우리은행 법인 계좌번호: 1002-123-456789",
    "  - 입금 시 위 계좌로 송금 바람",
    "",
    "■ 비고",
    "  본 문서는 SecurityCritic 차단 테스트용 가상 데이터입니다.",
    "  실제 인물·계좌·카드와 무관합니다.",
]

# 제목
page.insert_text((50, 60), title, fontname="malgun", fontsize=15, color=(0, 0, 0))

# 본문
y = 100
for line in lines:
    page.insert_text((50, y), line, fontname="malgun", fontsize=11, color=(0.05, 0.05, 0.05))
    y += 22

doc.save(str(OUT))
doc.close()
print(f"Saved: {OUT} ({OUT.stat().st_size:,} bytes)")
