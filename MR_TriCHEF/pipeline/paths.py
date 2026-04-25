"""Paths — 고정 경로 상수.

- Movie 임베딩: Data/embedded_DB/Movie/
- Music 임베딩: Data/embedded_DB/Rec/
- 테스트 소스:
    · Data/raw_DB/Movie/훤_youtube_1차/*.mp4
    · Data/raw_DB/Rec/YS_1차/*.m4a
"""
from __future__ import annotations

from pathlib import Path

# MR_TriCHEF/pipeline/paths.py → parents[2] == DB_insight/
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "Data"

RAW_ROOT       = DATA_ROOT / "raw_DB"
EMBEDDED_ROOT  = DATA_ROOT / "embedded_DB"

# 스캔 범위 — rglob 으로 재귀 (서브디렉토리 포함)
MOVIE_RAW_DIR  = RAW_ROOT / "Movie"   # 훤_youtube_1차 + 훤_youtube_2차 + 정혜_BGM_1차 전체
MUSIC_RAW_DIR  = RAW_ROOT / "Rec"     # YS_1차 + 태윤_1차/** 전체

MOVIE_CACHE_DIR = EMBEDDED_ROOT / "Movie"
MUSIC_CACHE_DIR = EMBEDDED_ROOT / "Rec"

for d in (MOVIE_CACHE_DIR, MUSIC_CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)

from ._extensions import MOVIE_EXTS, MUSIC_EXTS

# 모델 식별자 (로컬 HF 캐시)
MODEL_WHISPER = "large-v3"                                # faster-whisper
# Doc/Img 파리티 — naflex(가변 aspect) + dinov2-large(1024d)
MODEL_SIGLIP2 = "google/siglip2-so400m-patch16-naflex"
MODEL_DINOV2  = "facebook/dinov2-large"
MODEL_BGEM3   = "BAAI/bge-m3"

# [항목5] Whisper LoRA 어댑터 경로 — "" = 베이스 large-v3 사용.
# 한국어 방송/음원 도메인 fine-tuned 체크포인트 경로로 교체하면 자동 적용.
# 예: WHISPER_ADAPTER_PATH = "Data/models/whisper-ko-broadcast-lora"
WHISPER_ADAPTER_PATH: str = ""
