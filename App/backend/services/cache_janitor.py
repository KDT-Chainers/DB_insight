"""인덱싱 작업의 부분 캐시(orphan) 자동 정리.

배경:
  av_embed.py 는 `tempfile.mkdtemp(prefix="app_movie_"|"app_music_")` 로
  임시 작업 폴더를 만들고 finally 블록에서 정리한다. 그러나 사용자가
  exe 를 강제 종료하거나 OS 가 프로세스를 죽이면 finally 가 실행되지 않아
  stale 폴더가 OS 임시 디렉토리에 누적된다 (수 GB 단위 가능).

해결:
  /api/index/start 호출 직전 또는 사용자가 명시 호출 시
  `cleanup_stale_caches()` 가 일정 시간(>1h) 이상 미사용 stale 폴더를 제거.

설계:
  - psutil 로 살아있는 python 프로세스 목록 확인 (혹시라도 진행 중이면 보호)
  - mtime 기준 staleness 판단 (1시간 미동작 = 누구도 안 쓰는 것으로 간주)
  - 안전 prefix 검사 (app_movie_ / app_music_) — 다른 임시 폴더 영향 X
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

# 정리 대상 prefix — av_embed.py 의 mkdtemp prefix 와 1:1 매칭.
_PREFIXES = ("app_movie_", "app_music_")

# stale 판정 임계: 마지막 수정 시각 이후 N초 미사용 → 정리 대상.
_STALE_SECONDS = 3600  # 1시간


def _candidate_dirs(temp_root: Path) -> Iterable[Path]:
    """OS 임시 디렉토리 1단계에서 prefix 매칭 폴더만 yield."""
    try:
        for entry in temp_root.iterdir():
            try:
                if not entry.is_dir():
                    continue
                if any(entry.name.startswith(p) for p in _PREFIXES):
                    yield entry
            except OSError:
                continue
    except OSError as e:
        logger.warning(f"[cache_janitor] temp 스캔 실패: {e}")


def _is_stale(d: Path, now: float, threshold_sec: int) -> bool:
    """폴더 자체 mtime 기준. (활성 작업이면 ffmpeg 가 계속 파일 추가 → mtime 갱신.)"""
    try:
        return (now - d.stat().st_mtime) > threshold_sec
    except OSError:
        return False


def cleanup_stale_caches(temp_root: Path | None = None,
                         threshold_sec: int | None = None) -> dict:
    """OS 임시 디렉토리의 stale 인덱싱 임시 폴더 제거.

    Args:
        temp_root: 검사 디렉토리. None = `tempfile.gettempdir()`.
        threshold_sec: stale 판정 임계초. None = 기본 1시간.

    Returns:
        { "scanned": N, "removed": M, "freed_bytes": B }
    """
    root = temp_root or Path(tempfile.gettempdir())
    thr = _STALE_SECONDS if threshold_sec is None else int(threshold_sec)
    now = time.time()

    scanned = 0
    removed = 0
    freed = 0
    for d in _candidate_dirs(root):
        scanned += 1
        if not _is_stale(d, now, thr):
            continue
        # 크기 추정 (실패해도 무시)
        try:
            size = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
        except Exception:
            size = 0
        try:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
            freed += size
            logger.info(f"[cache_janitor] removed stale {d.name} ({size:,} bytes)")
        except Exception as e:
            logger.warning(f"[cache_janitor] {d.name} 제거 실패: {e}")

    return {"scanned": scanned, "removed": removed, "freed_bytes": freed}
