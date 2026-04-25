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
    # [DEPRECATED] v2 P1 에서 e5 → BGE-M3 전환 (bgem3_caption_im). 실사용처 없음.
    #   key 는 설정 파일 하위 호환성 위해 당분간 유지, 신규 코드 참조 금지.
    "MODEL_IM_E5LARGE":   "intfloat/multilingual-e5-large",
    "MODEL_IM_BGEM3":     "BAAI/bge-m3",  # 실사용 (bgem3_caption_im)
    "MODEL_Z_DINOV2":     "facebook/dinov2-large",
    # Img 캡션용 실사용 모델. 과거 3B 계열 계획(dead config) → 2B NF4 로 정착.
    "MODEL_QWEN_VL":      "Qwen/Qwen2-VL-2B-Instruct",

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
    "BATCH_IMG": 64,
    "BATCH_TXT": 128,

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
    "INT8_Z_DINOV2": True,    # 활성화 — RTX 4070 8GB VRAM 절감 -0.65GB

    # [양자화] SigLIP2 Re축 INT8 (FP16 1.0GB → INT8 0.50GB)
    # ViT 계열 임베딩 품질 변화 < 0.5%. DINOv2와 동일 BitsAndBytes 패턴.
    "INT8_RE_SIGLIP2": True,  # 활성화 — RTX 4070 8GB VRAM 절감 -0.50GB

    # [Doc Im_body fusion] PDF 본문 텍스트 Im 가중치
    # Im_fused = DOC_IM_ALPHA * Im_caption + (1-DOC_IM_ALPHA) * Im_body
    # Phase 4-2 튜닝 (LOO eval, n=150):
    #   α=0.20 → R@5 0.907 (dense), 0.900 (+sparse)  — 최적
    #   α=0.35 → R@5 0.880 (dense), 0.900 (+sparse)  — 이전 기본값
    #   α=1.00 → R@5 0.000  (Im_body 무시 시 본문 검색 완전 실패)
    # proxy keyword bench 와 non-regression 동시 달성.
    "DOC_IM_ALPHA": 0.20,

    # [ASF default] LOO/E2E/local_bench 모든 벤치에서 ASF on이 -3~20pp 손해 (2026-04-25 분석).
    #   LOO R@1: dense+sparse 83.3% → +ASF 63.3% (-20pp)
    #   E2E hit_rate: 53.3% → +ASF 43.3% (-10pp)
    #   원인: ASF keyword-set 컷오프가 vocab 미포함어("탄소중립" 등) 과잉 필터링.
    # 필요 시 search(use_asf=True) 명시적 호출로 활성 가능.
    "USE_ASF_DEFAULT": False,

    # [Img 3-stage caption fusion] BLIP v2 스타일 L1/L2/L3 캡션 가중치.
    # cache_img_Im_L1/L2/L3.npy 모두 존재 시 자동 활성화 (build_img_caption_triple.py).
    # L1(짧은 주제) 0.15, L2(키워드) 0.25, L3(상세 묘사) 0.60 — 상세도 비례.
    "IMG_IM_L1_ALPHA": 0.15,
    "IMG_IM_L2_ALPHA": 0.25,
    "IMG_IM_L3_ALPHA": 0.60,

    # LangGraph
    "GRAPH_MAX_ITER": 3,
    "GRAPH_HI_MARGIN": 0.030,
    "GRAPH_HN_MARGIN": 0.020,
    # [MR_TriCHEF graph] z-score 기반 confidence gate 임계값.
    # nodes.py 는 독립 실행이므로 env var TRICHEF_GRAPH_TAU_HIGH / LOW 로 오버라이드.
    # 여기는 단일 진실 원천(문서용) — App 프로세스에서도 읽어 nodes 로 env 주입 가능.
    "GRAPH_TAU_HIGH": 3.0,
    "GRAPH_TAU_LOW":  1.0,
    "GRAPH_MAX_TRIES": 2,
}

# ── 런타임 체크 ────────────────────────────────────────────────────────
#   INT8 양자화 플래그가 True 인데 bitsandbytes 가 없으면, 로더마다 FP16 fallback
#   되는 silent 동작. 시작 시점에서 한 번 명시적으로 경고.
def _check_int8_support() -> None:
    if TRICHEF_CFG.get("INT8_Z_DINOV2") or TRICHEF_CFG.get("INT8_RE_SIGLIP2"):
        try:
            import bitsandbytes  # noqa: F401
        except ImportError:
            import logging
            logging.getLogger("config").warning(
                "[config] INT8_Z_DINOV2/INT8_RE_SIGLIP2=True 이지만 bitsandbytes "
                "미설치 — FP16 fallback 동작. VRAM 절감 효과 없음. "
                "`pip install bitsandbytes` 로 활성화 가능."
            )

_check_int8_support()

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
