"""인덱싱 작업 예상 소요 시간 추정.

선택된 파일 목록 → 예상 총 시간(초) 계산.
- 이미 인덱싱된 파일(SHA 일치 가능)은 SHA-256 skip overhead 만 (~0.05s)
- 신규 파일은 type + 파일 크기 기반 휴리스틱

휴리스틱 계수는 NVDEC + Whisper batched + GPU bf16 reranker 환경(RTX 4070
Laptop) 측정값에서 도출:
  - doc:   5s base + 1.0s/MB    (PDF 페이지 렌더 + DINOv2/SigLIP2 임베딩)
  - image: 0.4s + 0.1s/MB       (단일 SigLIP2 + DINOv2 forward)
  - video: 3s + 0.5s/MB         (NVDEC 프레임 + 배치 Whisper)
  - audio: 2s + 0.8s/MB         (배치 Whisper STT)

오차는 ±50% 수준이지만 사용자에게 "수십 초인지 수십 분인지" 직관 제공이 목적.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from services.registry_lookup import lookup as _lookup_indexed

# 확장자 → 도메인 매핑 (routes/index.py 와 일치).
# 직접 import 하지 않고 별도 정의해 의존 사이클 회피.
_DOC_EXTS   = {".pdf", ".docx", ".doc", ".hwp", ".hwpx", ".pptx", ".ppt",
               ".txt", ".md", ".html", ".htm", ".xlsx", ".xls"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".m4v"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma", ".opus"}

# 시간 추정 계수 — (base_seconds, seconds_per_mb)
_COEF = {
    "doc":   (5.0, 1.0),
    "image": (0.4, 0.1),
    "video": (3.0, 0.5),
    "audio": (2.0, 0.8),
}

# SHA-256 skip 케이스의 fixed overhead (디스크 read + hash compute).
# 평균 작은 파일 기준이며 큰 영상은 ~0.5s 까지 늘어날 수 있어 상한 설정.
_SKIP_OVERHEAD_BASE = 0.05
_SKIP_OVERHEAD_PER_MB = 0.005   # 1GB → 5s


def _file_type(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    if ext in _DOC_EXTS:   return "doc"
    if ext in _IMAGE_EXTS: return "image"
    if ext in _VIDEO_EXTS: return "video"
    if ext in _AUDIO_EXTS: return "audio"
    return None


def _size_mb(path: str) -> float:
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except OSError:
        return 0.0


def estimate(paths: Iterable[str]) -> dict:
    """선택 파일 리스트 → 추정 정보.

    Returns:
        {
          "total_seconds": float,
          "skipped_count": int,    # registry 일치(이미 인덱싱) 추정
          "new_count":     int,    # 실제 임베딩 예정
          "unsupported":   int,    # 확장자 미지원
          "by_type": { "doc":{count,sec}, ... }   # 신규만 합산
        }
    """
    paths = list(paths or [])
    if not paths:
        return {"total_seconds": 0.0, "skipped_count": 0,
                "new_count": 0, "unsupported": 0, "by_type": {}}

    indexed_map = _lookup_indexed(paths)
    total = 0.0
    skipped = 0
    new = 0
    unsupported = 0
    by_type: dict[str, dict] = {}

    for p in paths:
        ftype = _file_type(p)
        if ftype is None:
            unsupported += 1
            continue
        size_mb = _size_mb(p)

        if indexed_map.get(p, {}).get("indexed"):
            skipped += 1
            total += _SKIP_OVERHEAD_BASE + _SKIP_OVERHEAD_PER_MB * size_mb
            continue

        new += 1
        base, per_mb = _COEF[ftype]
        sec = base + per_mb * size_mb
        total += sec
        slot = by_type.setdefault(ftype, {"count": 0, "seconds": 0.0})
        slot["count"]   += 1
        slot["seconds"] += sec

    return {
        "total_seconds": round(total, 1),
        "skipped_count": skipped,
        "new_count":     new,
        "unsupported":   unsupported,
        "by_type":       {k: {"count": v["count"], "seconds": round(v["seconds"], 1)}
                          for k, v in by_type.items()},
    }
