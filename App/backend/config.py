"""
경로 설정 중앙 관리

타입별 하위 폴더 구조:
  embedded_DB/
    Movie/   ← 영상 벡터 (ChromaDB)
    Doc/     ← 문서 벡터
    Img/     ← 이미지 벡터
    Rec/     ← 음성 벡터

  extracted_DB/
    Movie/   ← 영상 캡션·STT 캐시
    Doc/     ← 문서 추출 캐시
    Img/     ← 이미지 캡션 캐시
    Rec/     ← 음성 STT 캐시
"""

from pathlib import Path

DATA_ROOT    = Path(r"C:\Honey\DB_insight\Data")
EMBEDDED_DB  = DATA_ROOT / "embedded_DB"
EXTRACTED_DB = DATA_ROOT / "extracted_DB"

# ── 타입별 하위 폴더 ──────────────────────────────────────
EMBEDDED_DB_VIDEO = EMBEDDED_DB  / "Movie"
EMBEDDED_DB_DOC   = EMBEDDED_DB  / "Doc"
EMBEDDED_DB_IMAGE = EMBEDDED_DB  / "Img"
EMBEDDED_DB_AUDIO = EMBEDDED_DB  / "Rec"

EXTRACTED_DB_VIDEO = EXTRACTED_DB / "Movie"
EXTRACTED_DB_DOC   = EXTRACTED_DB / "Doc"
EXTRACTED_DB_IMAGE = EXTRACTED_DB / "Img"
EXTRACTED_DB_AUDIO = EXTRACTED_DB / "Rec"

# ── 디렉토리 자동 생성 ─────────────────────────────────────
for _d in [
    EMBEDDED_DB_VIDEO, EMBEDDED_DB_DOC, EMBEDDED_DB_IMAGE, EMBEDDED_DB_AUDIO,
    EXTRACTED_DB_VIDEO, EXTRACTED_DB_DOC, EXTRACTED_DB_IMAGE, EXTRACTED_DB_AUDIO,
]:
    _d.mkdir(parents=True, exist_ok=True)
