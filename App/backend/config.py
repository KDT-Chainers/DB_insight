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

import os
from pathlib import Path

_DEFAULT_DATA = Path(__file__).resolve().parents[2] / "Data"
DATA_ROOT    = Path(os.environ.get("DB_INSIGHT_DATA", str(_DEFAULT_DATA)))
EMBEDDED_DB  = DATA_ROOT / "embedded_DB"
EXTRACTED_DB = DATA_ROOT / "extracted_DB"
RAW_DB       = DATA_ROOT / "raw_DB"

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
    RAW_DB / "Img", RAW_DB / "Doc",
]:
    _d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# TRI-CHEF 설정 (feature/trichef-port)
# ─────────────────────────────────────────────────────────────

TRICHEF_CFG = {
    # 모델 ID (HuggingFace)
    "MODEL_RE_SIGLIP2":   "google/siglip2-so400m-patch16-naflex",
    "MODEL_IM_E5LARGE":   "intfloat/multilingual-e5-large",
    "MODEL_Z_DINOV2":     "facebook/dinov2-large",
    "MODEL_QWEN_VL":      "Qwen/Qwen2.5-VL-3B-Instruct",

    # 벡터 차원 (모델 결정값, 수정 금지)
    "DIM_RE": 1152,
    "DIM_IM": 1024,
    "DIM_Z":  1024,

    # FAR / 임계값 (Data-adaptive 재보정이 덮어씀)
    "FAR_IMG":      0.20,
    "FAR_DOC_TEXT": 0.05,
    "FAR_DOC_PAGE": 0.05,

    # 쿼리 확장
    # [W5-1 ROLLBACK 2026-04-24] N=5 실측 결과: p95 +167ms, recall/conf 개선 0.
    # paraphrase 비용만 증가하고 평균 벡터 품질은 이미 N=3 에서 포화. N=3 복원.
    "EXPAND_QUERY_ENABLED": True,
    "EXPAND_QUERY_N": 3,

    # 배치
    "BATCH_IMG": 8,
    "BATCH_TXT": 32,

    # 디바이스
    "DEVICE": "cuda" if os.environ.get("FORCE_CPU") != "1" else "cpu",

    # 컬렉션명 (기존 files_doc/files_image 와 분리)
    "COL_DOC_TEXT": "trichef_doc_text",
    "COL_DOC_PAGE": "trichef_doc_page",
    "COL_IMAGE":    "trichef_image",

    # Hard-Neg Cat-Affinity 마진
    "CAT_HN_MARGIN": 0.02,

    # [양자화] DINOv2 Z축 INT8 (FP16 1.3GB → INT8 0.65GB)
    # True 로 설정 시 bitsandbytes INT8 적용. 임베딩 품질 변화 < 0.5%.
    "INT8_Z_DINOV2": False,    # DINOv2: INT8 -> FP16 (Windows 호환성)

    # [양자화] SigLIP2 Re축 INT8 (FP16 1.0GB → INT8 0.50GB)
    # ViT 계열 임베딩 품질 변화 < 0.5%. DINOv2와 동일 BitsAndBytes 패턴.
    "INT8_RE_SIGLIP2": False,  # SigLIP2: INT8 -> FP16 (Windows 호환성)

    # [Doc Im_body fusion] PDF 본문 텍스트 Im 가중치
    # Im_fused = DOC_IM_ALPHA * Im_caption + (1-DOC_IM_ALPHA) * Im_body
    # 0.35 = 캡션 35%, 본문 65% (텍스트 밀도 높은 문서 기준 최적화)
    "DOC_IM_ALPHA": 0.35,

    # LangGraph
    "GRAPH_MAX_ITER": 3,
    "GRAPH_HI_MARGIN": 0.030,
    "GRAPH_HN_MARGIN": 0.020,
}

# PATHS dict — TRI-CHEF 모듈 호환 (문자열 경로)
PATHS = {
    "DATA_ROOT":     str(DATA_ROOT),
    "EMBEDDED_DB":   str(EMBEDDED_DB),
    "EXTRACTED_DB":  str(EXTRACTED_DB),
    "RAW_DB":        str(RAW_DB),
    # TRI-CHEF 캐시 경로 (기존 Img/Doc 폴더 재사용)
    "TRICHEF_IMG_CACHE":   str(EMBEDDED_DB_IMAGE),
    "TRICHEF_DOC_CACHE":   str(EMBEDDED_DB_DOC),
    "TRICHEF_IMG_EXTRACT": str(EXTRACTED_DB_IMAGE),
    "TRICHEF_DOC_EXTRACT": str(EXTRACTED_DB_DOC),
    # [W6-AV] Movie/Music(AV) 캐시 경로. 미정의 시 TriChefEngine 이 AV 도메인 skip.
    "TRICHEF_MOVIE_CACHE":   str(EMBEDDED_DB_VIDEO),
    "TRICHEF_MUSIC_CACHE":   str(EMBEDDED_DB_AUDIO),
    "TRICHEF_MOVIE_EXTRACT": str(EXTRACTED_DB_VIDEO),
    "TRICHEF_MUSIC_EXTRACT": str(EXTRACTED_DB_AUDIO),
    # TRI-CHEF 전용 ChromaDB 경로 (기존 컬렉션과 분리)
    "TRICHEF_CHROMA":      str(EMBEDDED_DB / "trichef"),
}

# TRI-CHEF 필요 하위 폴더 자동 생성
for _p in (
    EXTRACTED_DB_IMAGE / "captions",
    EXTRACTED_DB_IMAGE / "tags",
    EXTRACTED_DB_DOC   / "page_images",
    EXTRACTED_DB_DOC   / "captions",
    EXTRACTED_DB_DOC   / "chunks",
    EMBEDDED_DB        / "trichef",
):
    _p.mkdir(parents=True, exist_ok=True)
