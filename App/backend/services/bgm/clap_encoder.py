"""CLAP (Contrastive Language-Audio Pretraining) 텍스트·오디오 듀얼 인코더.

기본 모델: laion/clap-htsat-unfused (HuggingFace transformers)
  - 텍스트 임베딩: 512d
  - 오디오 임베딩: 512d
  - 입력 오디오 샘플레이트: 48000

GPU 가용 시 자동 cuda. CPU fallback 가능 (속도 ↓).

런타임 특성:
  - 1회 모델 로드 ~3GB VRAM
  - 30s 클립 임베딩 ~50ms (RTX 4070 Laptop)
  - lazy import — `transformers`/`torch` 미설치 환경에서도 패키지 import 자체는 성공
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Iterable

import numpy as np

from . import bgm_config

logger = logging.getLogger(__name__)

_model = None
_processor = None
_lock = threading.Lock()
_device = bgm_config.DEVICE


def _l2(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    n = np.where(n < 1e-12, 1.0, n)
    return v / n


def _ensure_loaded() -> None:
    global _model, _processor
    if _model is not None and _processor is not None:
        return
    with _lock:
        if _model is not None and _processor is not None:
            return
        try:
            import torch
            from transformers import ClapModel, ClapProcessor
        except ImportError as e:
            raise ImportError(
                "CLAP은 transformers + torch 가 필요합니다. "
                "`pip install transformers torch` 후 재시도하세요."
            ) from e

        model_id = bgm_config.CLAP_MODEL
        logger.info(f"[bgm.clap] 모델 로드 시작: {model_id} (device={_device})")
        _processor = ClapProcessor.from_pretrained(model_id)
        m = ClapModel.from_pretrained(model_id)
        if _device == "cuda" and torch.cuda.is_available():
            m = m.to("cuda")
        m.eval()
        _model = m
        logger.info(f"[bgm.clap] 로드 완료. dim={bgm_config.CLAP_DIM}")


def is_loaded() -> bool:
    return _model is not None


def encode_text(texts: list[str] | str) -> np.ndarray:
    """텍스트 → (N, 512) L2-normalized."""
    _ensure_loaded()
    import torch

    if isinstance(texts, str):
        texts = [texts]
    if not texts:
        return np.zeros((0, bgm_config.CLAP_DIM), dtype=np.float32)
    inputs = _processor(text=texts, return_tensors="pt", padding=True)
    if _device == "cuda" and torch.cuda.is_available():
        inputs = {k: v.to("cuda") for k, v in inputs.items()}
    with torch.no_grad():
        feats = _model.get_text_features(**inputs)
    arr = feats.detach().cpu().numpy().astype(np.float32)
    return _l2(arr)


def encode_audio(waveforms: Iterable[np.ndarray]) -> np.ndarray:
    """오디오 배치 → (N, 512) L2-normalized.
    각 waveform은 48kHz mono float32 1D ndarray."""
    _ensure_loaded()
    import torch

    wavs = [np.asarray(w, dtype=np.float32) for w in waveforms]
    if not wavs:
        return np.zeros((0, bgm_config.CLAP_DIM), dtype=np.float32)
    # transformers v4.59+ deprecated `audios=` → `audio=`; v4.59 미만 호환을 위해 try-fallback.
    try:
        inputs = _processor(
            audio=wavs,
            sampling_rate=bgm_config.CLAP_SR,
            return_tensors="pt",
            padding=True,
        )
    except TypeError:
        inputs = _processor(
            audios=wavs,
            sampling_rate=bgm_config.CLAP_SR,
            return_tensors="pt",
            padding=True,
        )
    if _device == "cuda" and torch.cuda.is_available():
        inputs = {k: v.to("cuda") for k, v in inputs.items()}
    with torch.no_grad():
        feats = _model.get_audio_features(**inputs)
    arr = feats.detach().cpu().numpy().astype(np.float32)
    return _l2(arr)


def encode_audio_file(path: str | Path, *, max_seconds: float | None = None) -> np.ndarray:
    """파일 경로 → (512,) L2-normalized 오디오 임베딩."""
    from .audio_extract import load_wav

    if max_seconds is None:
        max_seconds = bgm_config.AUDIO_MAX_SECONDS
    y, _ = load_wav(path, sr=bgm_config.CLAP_SR, max_seconds=max_seconds)
    emb = encode_audio([y])
    return emb[0]
