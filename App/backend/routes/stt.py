"""routes/stt.py — 마이크 음성 텍스트 변환 (faster-whisper).

Electron 환경에서 webkitSpeechRecognition 이 동작 안 하므로,
프론트가 MediaRecorder 로 녹음한 audio blob 을 받아 서버에서 STT 한다.

POST /api/stt/transcribe
  multipart/form-data:
    - audio: webm/wav/mp3/m4a 등 오디오 파일
    - partial: "true" | "false"   (선택. partial=true 는 chunk 누적 변환용 — 동작은 동일)
  → { "text": str, "partial": bool, "ms": int }

faster-whisper medium 모델은 첫 호출 시 한번만 로드 (5~15초). 이후 호출은 빠름.
"""
from __future__ import annotations

import io
import logging
import os
import tempfile
import threading
import time
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

stt_bp = Blueprint("stt", __name__, url_prefix="/api/stt")

WHISPER_MODEL = "medium"
LANGUAGE      = "ko"

_lock = threading.Lock()
_whisper: Any = None
_load_failed: bool = False


def _get_whisper() -> Any:
    """faster-whisper 모델 lazy 싱글턴. 실패 시 None."""
    global _whisper, _load_failed
    if _load_failed:
        return None
    if _whisper is not None:
        return _whisper
    with _lock:
        if _load_failed:
            return None
        if _whisper is not None:
            return _whisper
        try:
            import torch
            from faster_whisper import WhisperModel
            device = "cuda" if torch.cuda.is_available() else "cpu"
            compute = "float16" if device == "cuda" else "int8"
            t0 = time.time()
            _whisper = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute)
            logger.info(
                "[stt] faster-whisper '%s' loaded (device=%s compute=%s) in %.2fs",
                WHISPER_MODEL, device, compute, time.time() - t0,
            )
            return _whisper
        except Exception as e:
            _load_failed = True
            logger.error("[stt] faster-whisper 로드 실패: %s", e)
            return None


def _transcribe_bytes(audio_bytes: bytes) -> str:
    """audio bytes → 텍스트. faster-whisper 가 ffmpeg 로 자동 디코딩."""
    model = _get_whisper()
    if model is None:
        return ""
    # faster-whisper 는 file-like / path 모두 받음. 임시파일이 가장 안정적.
    suffix = ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        segments, _info = model.transcribe(
            tmp_path,
            language=LANGUAGE,
            beam_size=1,        # chunk-based interim 용도라 빠르게
            vad_filter=False,   # 클라이언트 VAD 사용
            condition_on_previous_text=False,
        )
        text = "".join(seg.text for seg in segments).strip()
        return text
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@stt_bp.post("/transcribe")
def transcribe():
    """audio blob → 텍스트.

    멀티파트 'audio' 필드 또는 raw body 둘 다 허용 (raw 가 더 가벼움).
    """
    t0 = time.time()
    partial = request.args.get("partial", "false").lower() == "true" or \
              request.form.get("partial", "false").lower() == "true"

    audio_bytes: bytes | None = None
    if "audio" in request.files:
        audio_bytes = request.files["audio"].read()
    elif request.data:
        audio_bytes = request.data

    if not audio_bytes:
        return jsonify({"error": "audio 데이터 없음"}), 400

    try:
        text = _transcribe_bytes(audio_bytes)
    except Exception as e:
        logger.exception("[stt] transcribe 실패")
        return jsonify({"error": f"transcribe 실패: {e}"}), 500

    elapsed_ms = int((time.time() - t0) * 1000)
    logger.info("[stt] partial=%s bytes=%d ms=%d text=%r", partial, len(audio_bytes), elapsed_ms, text[:60])
    return jsonify({"text": text, "partial": partial, "ms": elapsed_ms})


@stt_bp.get("/status")
def status():
    """모델 로드 상태 확인."""
    loaded = _whisper is not None
    return jsonify({
        "loaded": loaded,
        "model": WHISPER_MODEL,
        "language": LANGUAGE,
        "load_failed": _load_failed,
    })


@stt_bp.post("/warmup")
def warmup():
    """모델 미리 로드 (선택). 첫 마이크 클릭 지연 방지."""
    t0 = time.time()
    m = _get_whisper()
    return jsonify({
        "loaded": m is not None,
        "ms": int((time.time() - t0) * 1000),
    })
