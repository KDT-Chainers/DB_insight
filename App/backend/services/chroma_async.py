"""ChromaDB upsert 비동기 배치 워커.

배경:
  incremental_runner._upsert_chroma 가 임베딩 직후 동기 호출 → 다음 파일의
  프레임 추출/ffmpeg 시작이 ChromaDB 디스크 I/O 가 끝날 때까지 대기.
  파일당 100~200ms 가 누적 → 9 파일 1~2 초 손실.

해결:
  단일 워커 스레드 + 큐 패턴.
  embedder 가 enqueue() 만 호출하고 즉시 다음 파일로 진행.
  워커가 큐를 드레인하며 ChromaDB upsert 수행.
  배치 종료 직전 drain_and_wait() 로 일관성 보장.

설계 원칙:
  - daemon thread — 메인 프로세스 종료 시 자동 정리
  - reload_engine 직전에 반드시 drain_and_wait 호출 → 검색 정합성 보장
  - 환경변수 OMC_DISABLE_CHROMA_ASYNC=1 로 OFF (디버깅용)
"""
from __future__ import annotations

import logging
import os
import queue
import threading
from typing import Any

logger = logging.getLogger(__name__)

# (collection_name, ids, embeddings, metadatas) tuple. None = sentinel(종료)
_q: "queue.Queue[Any]" = queue.Queue()
_worker: threading.Thread | None = None
_started = False
_lock = threading.Lock()
_drain_event = threading.Event()
_inflight = 0  # 처리 중인 작업 수 (0 = 모두 완료)


def _enabled() -> bool:
    return os.environ.get("OMC_DISABLE_CHROMA_ASYNC", "").strip().lower() not in ("1", "true", "yes")


def _worker_loop():
    """큐에서 upsert 작업을 꺼내 collection 별로 ChromaDB 에 commit."""
    global _inflight
    while True:
        item = _q.get()
        try:
            if item is None:
                return
            collection_callable, ids, embeddings, metadatas = item
            try:
                col = collection_callable()
                CHUNK = 5000  # ChromaDB max batch ~5461
                n = len(ids)
                for start in range(0, n, CHUNK):
                    end = start + CHUNK
                    col.upsert(
                        ids=ids[start:end],
                        embeddings=embeddings[start:end].tolist(),
                        metadatas=metadatas[start:end],
                    )
            except Exception as e:
                logger.warning(f"[chroma_async] upsert 실패: {e}")
        finally:
            with _lock:
                _inflight -= 1
                if _inflight <= 0:
                    _drain_event.set()
            _q.task_done()


def _ensure_started():
    global _worker, _started
    with _lock:
        if _started:
            return
        _worker = threading.Thread(target=_worker_loop, name="chroma-async-worker", daemon=True)
        _worker.start()
        _started = True


def enqueue_upsert(collection_callable, ids, embeddings, metadatas) -> None:
    """ChromaDB upsert 를 비동기 큐에 추가. 즉시 반환.

    Args:
        collection_callable: 0-arg 함수, ChromaDB collection 객체 반환.
                             (lazy 객체 생성 — 워커 thread 에서 실행)
        ids:        리스트
        embeddings: numpy ndarray (n, d)
        metadatas:  리스트
    """
    global _inflight
    if not _enabled():
        # 동기 폴백
        col = collection_callable()
        CHUNK = 5000
        for start in range(0, len(ids), CHUNK):
            end = start + CHUNK
            col.upsert(
                ids=ids[start:end],
                embeddings=embeddings[start:end].tolist(),
                metadatas=metadatas[start:end],
            )
        return
    _ensure_started()
    with _lock:
        _inflight += 1
        _drain_event.clear()
    _q.put((collection_callable, ids, embeddings, metadatas))


def drain_and_wait(timeout: float = 120.0) -> bool:
    """큐가 모두 비고 모든 in-flight 작업이 완료될 때까지 대기.

    배치 종료 시점(reload_engine 직전) 호출 필수.
    Returns:
        True = 정상 드레인, False = timeout.
    """
    if not _started:
        return True
    return _drain_event.wait(timeout=timeout)
