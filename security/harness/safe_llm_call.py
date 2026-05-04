"""
safe_llm_call.py
──────────────────────────────────────────────────────────────────────────────
LLM 호출 안정화 래퍼 (운영 품질 보강용).

보안 정책 판단을 대체하지 않는다.
역할:
  - timeout 초과 감지
  - 최소 retry
  - empty output 방지
  - 호출 로그 일원화
"""
from __future__ import annotations

import logging
import time
from typing import Callable

logger = logging.getLogger(__name__)


def safe_llm_call(
    call_fn: Callable[[], str],
    *,
    timeout_sec: float,
    max_retries: int = 1,
    call_name: str = "llm_call",
) -> str:
    """
    LLM 호출 함수를 안전하게 실행한다.

    Args:
        call_fn:     실제 LLM 호출 함수 (문자열 반환)
        timeout_sec: 호출 허용 시간(초)
        max_retries: 실패 시 재시도 횟수 (0이면 재시도 없음)
        call_name:   로그용 호출 이름
    """
    retries = max(0, int(max_retries))
    last_exc: Exception | None = None

    for attempt in range(retries + 1):
        started = time.monotonic()
        try:
            out = call_fn()
            elapsed = time.monotonic() - started
            if elapsed > float(timeout_sec):
                raise TimeoutError(
                    f"{call_name} timeout exceeded: {elapsed:.2f}s > {timeout_sec:.2f}s"
                )
            if not out or not str(out).strip():
                raise ValueError(f"{call_name} returned empty output")
            logger.info(
                "[safe_llm_call] %s ok (attempt=%d/%d, %.2fs)",
                call_name, attempt + 1, retries + 1, elapsed,
            )
            return str(out).strip()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            elapsed = time.monotonic() - started
            logger.warning(
                "[safe_llm_call] %s failed (attempt=%d/%d, %.2fs): %s",
                call_name, attempt + 1, retries + 1, elapsed, exc,
            )
            if attempt >= retries:
                break

    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"{call_name} failed without exception")

