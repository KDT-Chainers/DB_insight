"""DI_TriCHEF/z_axis/dinov2_z.py — DINOv2 구조비전 Z축 임베더.

이미지/문서 페이지 썸네일을 DINOv2 로 인코딩 → 기존 `Z=Im` 을 대체하는
독립 Z축 벡터(~768d) 를 생성.

모델: facebook/dinov2-base  (~330MB)
출력 파일(배치 시): Data/embedded_DB/trichef/{image,doc_page}/cache_Z_dinov2.npy

수식 영향: hermitian_score 의 C = q_Z·d_Z 항이 실질 독립 신호.
현재 쿼리 Z 는 이미지가 없어 0벡터 또는 text-to-dinov2 전용 projection 필요 →
**초기에는 Z 쿼리를 q_Im 으로 대체하고, β 가중치를 낮춰 안전 도입.**
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

MODEL_ID = "facebook/dinov2-base"
EMB_DIM = 768


class DinoV2ZEncoder:
    def __init__(self, model_id: str = MODEL_ID, device: str | None = None,
                 dtype: str = "float16"):
        self.model_id = model_id
        self.device = device
        self.dtype = dtype
        self._model = None
        self._processor = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoImageProcessor, AutoModel

        torch_dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16,
                       "float32": torch.float32}.get(self.dtype, torch.float16)
        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"[DINOv2-Z] loading {self.model_id} on {device} ({self.dtype})")
        self._processor = AutoImageProcessor.from_pretrained(self.model_id)
        self._model = AutoModel.from_pretrained(
            self.model_id, torch_dtype=torch_dtype,
        ).to(device).eval()
        self._device = device

    @staticmethod
    def _l2(x: np.ndarray) -> np.ndarray:
        n = np.linalg.norm(x, axis=-1, keepdims=True)
        return x / np.clip(n, 1e-12, None)

    def embed_images(self, images: list[Any], batch_size: int = 16) -> np.ndarray:
        """PIL 이미지 리스트 → (N, 768) L2-normalized 임베딩."""
        import torch

        if not images:
            return np.zeros((0, EMB_DIM), dtype=np.float32)
        self._load()

        all_feats: list[np.ndarray] = []
        for i in range(0, len(images), batch_size):
            chunk = images[i:i + batch_size]
            inputs = self._processor(images=chunk, return_tensors="pt").to(self._device)
            with torch.no_grad():
                out = self._model(**inputs)
            # DINOv2: pooler_output(CLS) → 구조 특징
            feats = out.pooler_output.float().cpu().numpy()
            all_feats.append(feats)
        arr = np.concatenate(all_feats, axis=0).astype(np.float32)
        return self._l2(arr)

    def embed_paths(self, paths: list[Path | str]) -> np.ndarray:
        from PIL import Image
        imgs = [Image.open(p).convert("RGB") for p in paths]
        return self.embed_images(imgs)
