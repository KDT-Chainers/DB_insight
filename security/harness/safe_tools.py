"""
safe_tools.py
──────────────────────────────────────────────────────────────────────────────
에이전트 권한 하네스(Harness).

각 에이전트가 사용할 수 있는 도구를 안전한 래퍼로 제한.

허용/금지 목록:
  UploadSecurityAgent : 파일 읽기, PII 탐지  — DB 쓰기·삭제·OS 명령 금지
  RetrievalAgent      : VectorDB 검색         — 파일 삭제·외부 API 금지
  ResponseAgent       : 응답 생성             — DB 직접 조회 금지
  Orchestrator        : 흐름 제어만           — 세 권한 동시 소유 금지

ABC 원칙 강제:
  에이전트 인스턴스 생성 시 capabilities 집합을 검사하여
  A+B+C 동시 소유 시 RuntimeError 발생.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Set

import config

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 권한 상수 (ABC 원칙)
# ──────────────────────────────────────────────────────────────────────────────

CAP_A = "untrusted_input"   # [A] 신뢰불가 입력 처리
CAP_B = "sensitive_data"    # [B] 민감 시스템/개인 데이터 접근
CAP_C = "state_change"      # [C] 외부 통신 또는 상태 변경


def enforce_abc(agent_name: str, capabilities: Set[str]) -> None:
    """
    ABC 원칙 위반 감지.
    A+B+C 세 가지를 동시에 소유하면 RuntimeError 발생.
    config.ABC_ENFORCEMENT = False 이면 경고만 출력.
    """
    if {CAP_A, CAP_B, CAP_C}.issubset(capabilities):
        msg = (
            f"[ABC 위반] '{agent_name}' 에이전트가 A+B+C 세 권한을 동시에 보유합니다. "
            "보안 원칙 위반입니다."
        )
        if config.ABC_ENFORCEMENT:
            raise RuntimeError(msg)
        else:
            logger.warning(msg)


# ──────────────────────────────────────────────────────────────────────────────
# 안전한 파일 읽기 래퍼
# ──────────────────────────────────────────────────────────────────────────────

def safe_read_file(path: str | Path) -> bytes:
    """
    파일을 읽기 전용으로 열어 바이트 반환.
    디렉토리 트래버설 방지: 절대 경로로 정규화 후 검사.
    """
    resolved = Path(path).resolve()

    # 금지 경로 (시스템 디렉토리 접근 방지)
    forbidden_prefixes = ["/etc", "/sys", "/proc", "/usr/bin", "/bin", "/sbin"]
    for forbidden in forbidden_prefixes:
        if str(resolved).startswith(forbidden):
            raise PermissionError(f"금지된 경로: {resolved}")

    if not resolved.exists():
        raise FileNotFoundError(f"파일 없음: {resolved}")

    with open(resolved, "rb") as f:
        return f.read()


# ──────────────────────────────────────────────────────────────────────────────
# 안전한 VectorDB 검색 래퍼
# ──────────────────────────────────────────────────────────────────────────────

def safe_vector_search(store: Any, query_embedding: Any, top_k: int) -> Any:
    """
    VectorDB 검색만 허용.
    삭제·전체 조회 같은 위험 작업은 이 래퍼를 통해 불가능.
    """
    if top_k > 50:
        raise ValueError(f"top_k 최대 50 초과 요청: {top_k} — 대량 조회 차단")
    return store.search(query_embedding, top_k=top_k)


# ──────────────────────────────────────────────────────────────────────────────
# 금지된 OS 명령 차단
# ──────────────────────────────────────────────────────────────────────────────

def block_os_command(command: str) -> None:
    """
    OS 명령 실행 시도를 항상 차단.
    에이전트가 os.system(), subprocess 등을 호출하지 못하도록
    이 함수를 통해 시도 자체를 기록·차단.
    """
    raise PermissionError(
        f"[하네스] OS 명령 실행이 금지되어 있습니다: '{command}'"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 안전한 외부 HTTP 래퍼 (Ollama 전용)
# ──────────────────────────────────────────────────────────────────────────────

ALLOWED_HOSTS = {"localhost", "127.0.0.1"}

def safe_http_post(url: str, payload: bytes, timeout: int) -> bytes:
    """
    허용된 호스트(localhost)로만 HTTP POST 가능.
    외부 인터넷 요청 차단.
    """
    import urllib.parse
    import urllib.request

    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""

    if host not in ALLOWED_HOSTS:
        raise PermissionError(
            f"[하네스] 외부 호스트 '{host}' 로의 HTTP 요청이 차단되었습니다. "
            f"허용 호스트: {ALLOWED_HOSTS}"
        )

    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ──────────────────────────────────────────────────────────────────────────────
# 안전한 파일 확장자 검증
# ──────────────────────────────────────────────────────────────────────────────

ALLOWED_EXTENSIONS = {".pdf", ".hwpx", ".png", ".jpg", ".jpeg", ".heic", ".webp"}

def validate_upload_file(path: str | Path) -> Path:
    """
    업로드 파일 확장자 및 크기 검증.
    허용되지 않은 파일 형식이면 ValueError 발생.
    """
    resolved = Path(path).resolve()
    ext = resolved.suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"허용되지 않은 파일 형식: '{ext}'. "
            f"허용 형식: {ALLOWED_EXTENSIONS}"
        )

    # 파일 크기 제한: 100MB
    max_size = 100 * 1024 * 1024
    size = resolved.stat().st_size
    if size > max_size:
        raise ValueError(
            f"파일 크기 초과: {size / 1024 / 1024:.1f}MB (최대 100MB)"
        )

    return resolved
