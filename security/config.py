"""
config.py — 프로젝트 전역 설정
환경변수(.env) 또는 직접 수정으로 조정 가능
"""
from __future__ import annotations
import os
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# 경로
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
VECTOR_DIR  = BASE_DIR / "vectordb" / "store"
AUDIT_DB    = BASE_DIR / "audit" / "audit.db"
# 원본 청크를 보호 저장하는 경로 (파일시스템 권한 700)
SECURE_STORE_DIR = BASE_DIR / "secure_store"
IMAGE_STORE_DIR  = SECURE_STORE_DIR / "images"   # 업로드 이미지 영구 보관

DATA_DIR.mkdir(exist_ok=True)
VECTOR_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_DB.parent.mkdir(exist_ok=True)
SECURE_STORE_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_STORE_DIR.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# 임베딩 모델 (로컬, 무료)
# ──────────────────────────────────────────────────────────────────────────────
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "snunlp/KR-SBERT-V40K-klueNLI-augSTS")
EMBEDDING_DIM   = 768

# ──────────────────────────────────────────────────────────────────────────────
# Qwen / Ollama 설정
# ──────────────────────────────────────────────────────────────────────────────
OLLAMA_URL        = os.getenv("OLLAMA_URL", "http://localhost:11434")
QWEN_MODEL        = os.getenv("QWEN_MODEL", "qwen2.5:7b")   # ollama pull qwen2.5:7b
QWEN_TIMEOUT_SEC  = int(os.getenv("QWEN_TIMEOUT_SEC", "60"))

# ──────────────────────────────────────────────────────────────────────────────
# 청킹
# ──────────────────────────────────────────────────────────────────────────────
CHUNK_SIZE    = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))

# ──────────────────────────────────────────────────────────────────────────────
# 검색
# ──────────────────────────────────────────────────────────────────────────────
TOP_K = int(os.getenv("TOP_K", "5"))

# Query rewrite / grounding gate
QUERY_REWRITE_ENABLED = os.getenv("QUERY_REWRITE_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
QUERY_REWRITE_MAX_CHARS = int(os.getenv("QUERY_REWRITE_MAX_CHARS", "160"))
GROUNDING_SIM_THRESHOLD = float(os.getenv("GROUNDING_SIM_THRESHOLD", "0.15"))
# SENSITIVE 질의는 마스킹으로 인해 유사도가 낮게 측정될 수 있어 일반보다 완화된 값 사용
# 여권 등 특정 키워드 질의는 GroundingGate에서 추가로 -0.08 적용
GROUNDING_SIM_THRESHOLD_SENSITIVE = float(os.getenv("GROUNDING_SIM_THRESHOLD_SENSITIVE", "0.38"))

# 보안 게이트웨이 — secure_index 접근 토큰 유효시간(초)
SECURE_TOKEN_TTL_SEC = int(os.getenv("SECURE_TOKEN_TTL_SEC", "300"))

# ──────────────────────────────────────────────────────────────────────────────
# 보안 에이전트: ABC 원칙
# 하나의 Agent 가 A(신뢰불가 입력) + B(민감데이터 접근) + C(외부통신/상태변경)
# 세 가지를 동시에 가지면 안 됨.
#
#  UploadSecurityAgent  → A 만 허용  (파일 검사, DB/외부 접근 금지)
#  RetrievalAgent       → B 만 허용  (VectorDB 읽기, 직접 외부통신 금지)
#  ResponseAgent        → C 만 허용  (응답 생성, 신뢰불가 입력 직접 처리 금지)
#  Orchestrator         → A·B·C 동시 보유 금지, 흐름 제어만
# ──────────────────────────────────────────────────────────────────────────────
ABC_ENFORCEMENT = True   # False 시 권한 검사 스킵 (개발 디버그용)
