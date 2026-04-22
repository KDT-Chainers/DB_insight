"""embedders/trichef/bgem3_caption_im.py — BGE-M3 Dense Im 축 (v2 P1).

e5-large 대체. 한국어↔영어 크로스링구얼 정렬 및 장문(8192 tokens) 대응.
Sparse/ColBERT 모드는 v2 P2, v3 P5에서 분리 투입.
"""
from __future__ import annotations

import logging
import threading

import numpy as np
import torch

from config import TRICHEF_CFG

logger = logging.getLogger(__name__)

_MODEL_ID = "BAAI/bge-m3"
_DEVICE   = TRICHEF_CFG["DEVICE"]
_lock  = threading.Lock()
_model = None


def _load():
    global _model
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        logger.info(f"[bgem3] 모델 로드: {_MODEL_ID} ({_DEVICE})")
        from FlagEmbedding import BGEM3FlagModel
        _model = BGEM3FlagModel(
            _MODEL_ID,
            use_fp16=(_DEVICE == "cuda"),
            devices=[_DEVICE] if _DEVICE == "cuda" else ["cpu"],
        )
        logger.info("[bgem3] 로드 완료")


@torch.inference_mode()
def embed_passage(texts: list[str], batch_size: int = 32,
                  max_length: int = 1024) -> np.ndarray:
    """장문 캡션(BLIP L3) 대응. (N, 1024) float32."""
    _load()
    if not texts:
        return np.zeros((0, TRICHEF_CFG["DIM_IM"]), dtype=np.float32)
    out = _model.encode(
        texts,
        batch_size=batch_size,
        max_length=max_length,
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )
    vecs = np.asarray(out["dense_vecs"], dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12
    return vecs / norms


@torch.inference_mode()
def embed_query(text: str, max_length: int = 256) -> np.ndarray:
    """쿼리 임베딩. BGE-M3는 prefix 불필요."""
    _load()
    out = _model.encode(
        [text],
        batch_size=1,
        max_length=max_length,
        return_dense=True,
    )
    v = np.asarray(out["dense_vecs"][0], dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-12)
