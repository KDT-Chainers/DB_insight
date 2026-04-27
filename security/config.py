"""
config.py — 프로젝트 전역 설정
환경변수(.env) 또는 직접 수정으로 조정 가능

진단: QWEN_TIMEOUT_SEC 등이 실제로 읽히는지 확인하려면 앱 실행 전에
  DEBUG_CONFIG=1
를 설정하면 stderr에 핵심 플래그·타임아웃·원시 env 문자열이 한 번 출력된다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# 경로
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
VECTOR_DIR  = BASE_DIR / "vectordb" / "store"
AUDIT_DB    = BASE_DIR / "audit" / "audit.db"
SECURE_STORE_DIR = BASE_DIR / "secure_store"
IMAGE_STORE_DIR  = SECURE_STORE_DIR / "images"

DATA_DIR.mkdir(exist_ok=True)
VECTOR_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_DB.parent.mkdir(parents=True, exist_ok=True)
SECURE_STORE_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_STORE_DIR.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# 임베딩 모델 (로컬)
# ──────────────────────────────────────────────────────────────────────────────
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "snunlp/KR-SBERT-V40K-klueNLI-augSTS")
EMBEDDING_DIM   = 768

# ──────────────────────────────────────────────────────────────────────────────
# Qwen / Ollama (선택)
# USE_QWEN=0 → 질의 분류 등에 Ollama 미사용, PRS 규칙 기반 분류.
# ──────────────────────────────────────────────────────────────────────────────
USE_QWEN = os.getenv("USE_QWEN", "0").strip().lower() in {"1", "true", "yes", "on"}
OLLAMA_URL       = os.getenv("OLLAMA_URL", "http://localhost:11434")
QWEN_MODEL       = os.getenv("QWEN_MODEL", "qwen2.5:3b")
# 타임아웃 내 응답 없으면 orchestrator 가 PRS 규칙 기반으로 폴백.
QWEN_TIMEOUT_SEC = int(os.getenv("QWEN_TIMEOUT_SEC", "15"))

# Summary Agent — USE_QWEN 과 독립적으로 동작.
# Ollama가 살아있으면 SUMMARY_USE_LLM=1 만으로 LLM 요약이 켜진다.
# CPU 환경에서도 qwen2.5:3b 기준 30~60초 안쪽이 보통. 꺼두면 추출 요약(품질 매우 낮음).
SUMMARY_MODEL       = os.getenv("SUMMARY_MODEL", "qwen2.5:3b")
SUMMARY_TIMEOUT_SEC = int(os.getenv("SUMMARY_TIMEOUT_SEC", "60"))  # CPU 환경 고려해 60s
SUMMARY_MAX_CHARS   = int(os.getenv("SUMMARY_MAX_CHARS", "1200"))  # 충분한 문맥 확보
SUMMARY_MAX_CHUNKS  = int(os.getenv("SUMMARY_MAX_CHUNKS", "5"))    # 더 많은 청크 참조
# USE_QWEN 과 무관하게 요약 LLM 사용 여부 단독 제어 (기본 켬)
SUMMARY_USE_LLM     = os.getenv("SUMMARY_USE_LLM", "1").strip().lower() in {"1", "true", "yes", "on"}
# Map-reduce 요약 — 청크 수가 이 임계값 이상이면 자동으로 map-reduce 분기.
# 각 group에 MAP_REDUCE_GROUP_SIZE 개씩 나눠 개별 요약 후 최종 reduce.
MAP_REDUCE_THRESHOLD  = int(os.getenv("MAP_REDUCE_THRESHOLD", "999"))  # 사실상 비활성화
MAP_REDUCE_GROUP_SIZE = int(os.getenv("MAP_REDUCE_GROUP_SIZE", "3"))

# ──────────────────────────────────────────────────────────────────────────────
# 청킹
# ──────────────────────────────────────────────────────────────────────────────
CHUNK_SIZE    = int(os.getenv("CHUNK_SIZE", "800"))   # 500 → 800: 짧은 목차 조각 감소
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))

# ──────────────────────────────────────────────────────────────────────────────
# 검색
# ──────────────────────────────────────────────────────────────────────────────
TOP_K = int(os.getenv("TOP_K", "5"))
# 요약·줄거리 질의는 더 넓게 검색해 문맥 손실을 줄인다 (safe_tools 상한 50 이내).
SUMMARY_TOP_K = int(os.getenv("SUMMARY_TOP_K", "20"))

# Query rewrite — USE_QWEN=1 일 때만 의미 있음; 기본 꺼짐(속도 우선).
QUERY_REWRITE_ENABLED = os.getenv("QUERY_REWRITE_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
QUERY_REWRITE_MAX_CHARS = int(os.getenv("QUERY_REWRITE_MAX_CHARS", "160"))
GROUNDING_SIM_THRESHOLD = float(os.getenv("GROUNDING_SIM_THRESHOLD", "0.15"))
# 요약·줄거리 등 짧은 질의 + 긴 본문 → 코사인이 낮게 나오기 쉬워 별도 임계값 사용
GROUNDING_SIM_THRESHOLD_SUMMARY = float(os.getenv("GROUNDING_SIM_THRESHOLD_SUMMARY", "0.07"))
GROUNDING_SIM_THRESHOLD_SENSITIVE = float(os.getenv("GROUNDING_SIM_THRESHOLD_SENSITIVE", "0.38"))
# Grounding 유사도 계산 시 본문 상한(초과분은 잘라냄) — 긴 소설/문서에서 임베딩 지연·UI 멈춤 방지
GROUNDING_EMBED_CONTEXT_MAX_CHARS = int(os.getenv("GROUNDING_EMBED_CONTEXT_MAX_CHARS", "3000"))

SECURE_TOKEN_TTL_SEC = int(os.getenv("SECURE_TOKEN_TTL_SEC", "300"))

# ──────────────────────────────────────────────────────────────────────────────
# PRS (privacy_risk_score.py)
# ──────────────────────────────────────────────────────────────────────────────
PRS_NORMAL_THRESHOLD    = float(os.getenv("PRS_NORMAL_THRESHOLD", "0.30"))
PRS_DANGEROUS_THRESHOLD = float(os.getenv("PRS_DANGEROUS_THRESHOLD", "0.65"))

# ──────────────────────────────────────────────────────────────────────────────
# 이미지 모자이크 / 마스킹
# ──────────────────────────────────────────────────────────────────────────────
MOSAIC_ENGINE = os.getenv("MOSAIC_ENGINE", "cv2")
MASKING_STYLE = os.getenv("MASKING_STYLE", "token")

# ──────────────────────────────────────────────────────────────────────────────
# ABC 원칙
# ──────────────────────────────────────────────────────────────────────────────
ABC_ENFORCEMENT = True

if os.getenv("DEBUG_CONFIG", "").strip().lower() in {"1", "true", "yes", "on"}:
    _raw_qwen_t = os.getenv("QWEN_TIMEOUT_SEC", "<unset>")
    print(
        "[DEBUG_CONFIG] loaded from "
        f"{Path(__file__).resolve()}\n"
        f"  USE_QWEN={USE_QWEN}  QWEN_TIMEOUT_SEC={QWEN_TIMEOUT_SEC}  (env QWEN_TIMEOUT_SEC={_raw_qwen_t!r})\n"
        f"  SUMMARY_USE_LLM={SUMMARY_USE_LLM}  SUMMARY_TIMEOUT_SEC={SUMMARY_TIMEOUT_SEC}\n"
        f"  QUERY_REWRITE_ENABLED={QUERY_REWRITE_ENABLED}  OLLAMA_URL={OLLAMA_URL!r}\n"
        f"  QWEN_MODEL={QWEN_MODEL!r}",
        file=sys.stderr,
        flush=True,
    )
