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
  - bgm:   1.0s + 0.2s/MB       (CLAP 임베딩 — Whisper 없이 빠름)

BGM vs audio 구분: 파일 경로에 "Bgm" 또는 "BGM" 폴더가 포함되면 bgm 타입.
(config.py: EXTRACTED_DB_BGM = .../Bgm, raw_DB/.../Bgm 등)

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

# [B1] BGM 폴더 키워드 — 경로에 포함되면 audio 대신 bgm 타입으로 처리.
# config.py 의 EXTRACTED_DB_BGM = .../Bgm 과 일치.
_BGM_PATH_KEYWORDS = {"bgm", "Bgm", "BGM"}

# 시간 추정 계수 — (base_seconds, seconds_per_mb)
_COEF = {
    "doc":   (5.0, 1.0),
    "image": (0.4, 0.1),
    "video": (3.0, 0.5),
    "audio": (2.0, 0.8),
    # [B1] BGM: CLAP 임베딩 — Whisper STT 없으므로 audio 대비 ~4배 빠름
    "bgm":   (1.0, 0.2),
}

# SHA-256 skip 케이스의 fixed overhead (디스크 read + hash compute).
# 평균 작은 파일 기준이며 큰 영상은 ~0.5s 까지 늘어날 수 있어 상한 설정.
_SKIP_OVERHEAD_BASE = 0.05
_SKIP_OVERHEAD_PER_MB = 0.005   # 1GB → 5s


def _file_type(path: str) -> str | None:
    """확장자 + 폴더 위치 기반 타입 결정.

    BGM 은 audio 와 동일한 확장자(.mp3/.wav 등)를 사용하지만
    CLAP 임베딩(Whisper STT 없음)으로 처리되어 시간이 크게 다르므로
    경로 내 Bgm/BGM 폴더 여부로 구분한다.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in _DOC_EXTS:   return "doc"
    if ext in _IMAGE_EXTS: return "image"
    if ext in _VIDEO_EXTS: return "video"
    if ext in _AUDIO_EXTS:
        # [B1] 경로 중 하나라도 BGM 폴더면 bgm 타입
        parts = set(Path(path).parts)
        if parts & _BGM_PATH_KEYWORDS:
            return "bgm"
        return "audio"
    return None


def _size_mb(path: str) -> float:
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except OSError:
        return 0.0


# ---------------------------------------------------------------------------
# [Phase 4] 메타데이터 기반 정밀 추정 헬퍼
# ---------------------------------------------------------------------------

def _ffprobe_duration(path: str, stream_type: str = "v") -> float | None:
    """ffprobe 로 지정 스트림의 재생 시간(초) 반환. 실패 시 None."""
    try:
        import subprocess, json as _json
        r = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                "-select_streams", f"{stream_type}:0",
                path,
            ],
            capture_output=True,
            timeout=3,
        )
        if r.returncode != 0:
            return None
        data = _json.loads(r.stdout)
        stream = (data.get("streams") or [{}])[0]
        dur = float(stream.get("duration") or 0)
        return dur if dur > 0 else None
    except Exception:
        return None


def _ffprobe_video_info(path: str) -> tuple[float, int, str] | None:
    """(duration_sec, height, codec) 반환. 실패 시 None."""
    try:
        import subprocess, json as _json
        r = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                "-select_streams", "v:0",
                path,
            ],
            capture_output=True,
            timeout=3,
        )
        if r.returncode != 0:
            return None
        data = _json.loads(r.stdout)
        stream = (data.get("streams") or [{}])[0]
        dur    = float(stream.get("duration") or 0)
        height = int(stream.get("height") or 720)
        codec  = stream.get("codec_name", "h264")
        return (dur, height, codec) if dur > 0 else None
    except Exception:
        return None


def _pdf_page_count(path: str) -> int | None:
    """PDF 페이지 수 반환. PyMuPDF → pdfplumber 순서로 시도. 실패 시 None."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(path)
        n = len(doc)
        doc.close()
        return n if n > 0 else None
    except Exception:
        pass
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            n = len(pdf.pages)
        return n if n > 0 else None
    except Exception:
        return None


def _meta_estimate(path: str, ftype: str) -> float | None:
    """메타데이터 기반 정밀 추정. 실패 시 None → 크기 기반 폴백."""
    base, _ = _COEF[ftype]

    if ftype == "video":
        info = _ffprobe_video_info(path)
        if info is None:
            return None
        dur, height, codec = info
        # 해상도 계수 (GPU 디코딩 처리량이 해상도에 비례)
        if   height >= 2160: res_coef = 3.0
        elif height >= 1080: res_coef = 1.5
        elif height >= 720:  res_coef = 1.0
        else:                res_coef = 0.7
        # H.265/HEVC 는 NVDEC 처리 빠름
        codec_coef = 0.8 if codec in ("hevc", "h265") else 1.0
        return base + 0.05 * dur * res_coef * codec_coef

    if ftype in ("audio", "bgm"):
        dur = _ffprobe_duration(path, stream_type="a")
        if dur is None:
            return None
        per_sec = 0.015 if ftype == "bgm" else 0.03
        return base + per_sec * dur

    if ftype == "doc":
        ext = os.path.splitext(path)[1].lower()
        if ext != ".pdf":
            return None  # PDF 외는 페이지 수 추출 어려움 → 크기 기반 폴백
        pages = _pdf_page_count(path)
        if pages is None:
            return None
        return base + 1.5 * pages

    return None


# [Phase 3] 비디오 5단계 가중치 — 각 스테이지가 전체 처리 시간에서 차지하는 비율.
# 측정 환경: RTX 4070 Laptop, NVDEC 프레임 추출, batched Whisper large-v3.
VIDEO_STAGE_WEIGHTS: dict[int, float] = {
    1: 0.10,   # 프레임 추출 (NVDEC)
    2: 0.35,   # SigLIP2 Re + DINOv2 Z 임베딩
    3: 0.40,   # Whisper STT (가장 오래 걸림)
    4: 0.10,   # BGE-M3 Im 임베딩
    5: 0.05,   # VectorDB 저장
}


def estimate_single(path: str, current_step: int | None = None) -> float:
    """현재 처리 중인 파일의 남은 시간 추정 (Phase 3).

    current_step: 1-indexed 스테이지 번호 (video 전용).
                  None 이면 파일 전체 추정 시간 반환.
    [Phase 4] 메타데이터 추정 우선, 실패 시 크기 기반 폴백.
    """
    ftype = _file_type(path)
    if ftype is None:
        return 0.0

    # [Phase 4] 메타데이터 기반 우선
    total_est = _meta_estimate(path, ftype)
    if total_est is None:
        base, per_mb = _COEF[ftype]
        total_est = base + per_mb * _size_mb(path)

    if ftype == "video" and current_step is not None:
        completed_weight = sum(
            w for step, w in VIDEO_STAGE_WEIGHTS.items()
            if step < current_step
        )
        remaining_weight = max(0.0, 1.0 - completed_weight)
        return total_est * remaining_weight

    return total_est


def estimate_file(path: str) -> float:
    """단일 파일의 원시 추정 시간 (registry 조회 없이, 신규 처리 가정).

    _run_job() 에서 완료된 파일의 done_estimate 누적에 사용.
    [Phase 4] 메타데이터 추정 우선, 실패 시 크기 기반 폴백.
    """
    ftype = _file_type(path)
    if ftype is None:
        return 0.0
    meta = _meta_estimate(path, ftype)
    if meta is not None:
        return meta
    base, per_mb = _COEF[ftype]
    return base + per_mb * _size_mb(path)


def estimate(paths: Iterable[str]) -> dict:
    """선택 파일 리스트 → 추정 정보.

    Returns:
        {
          "total_seconds": float,   # 신규 + skip overhead 합산
          "new_seconds":   float,   # 신규 파일만의 추정 시간
          "skip_seconds":  float,   # 이미 인덱싱된 파일 처리 overhead
          "skipped_count": int,     # registry 일치(이미 인덱싱) 추정
          "new_count":     int,     # 실제 임베딩 예정
          "unsupported":   int,     # 확장자 미지원
          "by_type": { "doc":{count,sec}, ... }   # 신규만 합산
        }
    """
    paths = list(paths or [])
    if not paths:
        return {"total_seconds": 0.0, "new_seconds": 0.0, "skip_seconds": 0.0,
                "skipped_count": 0, "new_count": 0, "unsupported": 0, "by_type": {}}

    indexed_map = _lookup_indexed(paths)
    total = 0.0
    new_sec = 0.0
    skip_sec = 0.0
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
            oh = _SKIP_OVERHEAD_BASE + _SKIP_OVERHEAD_PER_MB * size_mb
            skip_sec += oh
            total += oh
            continue

        new += 1
        # [Phase 4] 메타데이터 기반 우선, 실패 시 크기 기반 폴백
        meta_sec = _meta_estimate(p, ftype)
        if meta_sec is not None:
            sec = meta_sec
        else:
            base, per_mb = _COEF[ftype]
            sec = base + per_mb * size_mb
        new_sec += sec
        total += sec
        slot = by_type.setdefault(ftype, {"count": 0, "seconds": 0.0})
        slot["count"]   += 1
        slot["seconds"] += sec

    return {
        "total_seconds": round(total, 1),
        "new_seconds":   round(new_sec, 1),
        "skip_seconds":  round(skip_sec, 1),
        "skipped_count": skipped,
        "new_count":     new,
        "unsupported":   unsupported,
        "by_type":       {k: {"count": v["count"], "seconds": round(v["seconds"], 1)}
                          for k, v in by_type.items()},
    }
