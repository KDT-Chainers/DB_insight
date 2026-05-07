"""MR_TriCHEF/pipeline/audio_z_clap.py — CLAP(Contrastive Language-Audio) Z축 임베더.

현재 Music 은 Z = zeros → 실질 1축. CLAP 으로 **오디오 의미 임베딩**을 Z축에 주입해
3축 Hermitian 설계를 복원.

모델: laion/clap-htsat-fused  (~1.5GB)
출력 dim: 512
입력: 16kHz mono wav (frame_sampler 가 이미 생성하는 포맷과 호환)

쿼리 Z: 동일 CLAP text encoder 로 텍스트 → 512d → Im 축과 동시 정렬 가능.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

MODEL_ID = "laion/clap-htsat-fused"
EMB_DIM = 512
SAMPLE_RATE = 48000  # CLAP 기본 SR. 16k 입력은 리샘플.


class ClapZEncoder:
    def __init__(self, model_id: str = MODEL_ID, device: str | None = None,
                 dtype: str = "float32"):
        self.model_id = model_id
        self.device = device
        self.dtype = dtype
        self._model = None
        self._processor = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import ClapModel, ClapProcessor

        torch_dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16,
                       "float32": torch.float32}.get(self.dtype, torch.float32)
        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"[CLAP-Z] loading {self.model_id} on {device} ({self.dtype})")
        self._processor = ClapProcessor.from_pretrained(self.model_id)
        self._model = ClapModel.from_pretrained(
            self.model_id, torch_dtype=torch_dtype,
        ).to(device).eval()
        self._device = device

    @staticmethod
    def _l2(x: np.ndarray) -> np.ndarray:
        n = np.linalg.norm(x, axis=-1, keepdims=True)
        return x / np.clip(n, 1e-12, None)

    def _load_wav(self, path: Path) -> np.ndarray:
        import librosa
        y, _ = librosa.load(str(path), sr=SAMPLE_RATE, mono=True)
        return y.astype(np.float32)

    def embed_audio_paths(self, paths: list[Path | str],
                          batch_size: int = 4) -> np.ndarray:
        import torch

        if not paths:
            return np.zeros((0, EMB_DIM), dtype=np.float32)
        self._load()

        wavs = [self._load_wav(Path(p)) for p in paths]
        all_feats: list[np.ndarray] = []
        for i in range(0, len(wavs), batch_size):
            chunk = wavs[i:i + batch_size]
            inputs = self._processor(audios=chunk, sampling_rate=SAMPLE_RATE,
                                     return_tensors="pt").to(self._device)
            with torch.no_grad():
                feats = self._model.get_audio_features(**inputs)
            all_feats.append(feats.float().cpu().numpy())
        arr = np.concatenate(all_feats, axis=0).astype(np.float32)
        return self._l2(arr)

    def embed_text(self, texts: list[str]) -> np.ndarray:
        """쿼리 텍스트 → 동일 CLAP latent 공간 (512d)."""
        import torch

        if not texts:
            return np.zeros((0, EMB_DIM), dtype=np.float32)
        self._load()
        inputs = self._processor(text=texts, padding=True,
                                 return_tensors="pt").to(self._device)
        with torch.no_grad():
            feats = self._model.get_text_features(**inputs)
        return self._l2(feats.float().cpu().numpy()).astype(np.float32)
