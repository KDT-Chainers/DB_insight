"""BGE-M3 dense 텍스트 임베딩 (1024d)."""
from __future__ import annotations

import gc

import numpy as np
import torch

from .paths import MODEL_BGEM3


class BGEM3Encoder:
    def __init__(self, model_id: str = MODEL_BGEM3, device: str = "cuda"):
        from FlagEmbedding import BGEM3FlagModel
        self.model = BGEM3FlagModel(model_id, use_fp16=True, device=device)

    def embed(self, texts: list[str], batch: int = 16) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1024), dtype=np.float32)
        # FlagEmbedding 이 내부적으로 L2 정규화 수행 (normalize_embeddings=True)
        out = self.model.encode(
            texts, batch_size=batch, max_length=512,
            return_dense=True, return_sparse=False, return_colbert_vecs=False,
        )
        dense = out["dense_vecs"]
        if isinstance(dense, torch.Tensor):
            dense = dense.float().cpu().numpy()
        return dense.astype(np.float32)

    def unload(self):
        del self.model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
