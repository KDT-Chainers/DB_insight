"""embedders/trichef/siglip2_re.py — Re 축 (SigLIP2-SO400M 1152d).

이미지와 텍스트 양쪽을 동일 공간에 임베딩하여 cross-modal 코사인 유사도를 얻는다.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

from config import TRICHEF_CFG

logger = logging.getLogger(__name__)

_MODEL_ID = TRICHEF_CFG["MODEL_RE_SIGLIP2"]
_DEVICE   = TRICHEF_CFG["DEVICE"]
_BATCH    = TRICHEF_CFG["BATCH_IMG"]

_model: AutoModel | None = None
_proc:  AutoProcessor | None = None


def _load() -> None:
    global _model, _proc
    if _model is not None:
        return
    logger.info(f"[siglip2_re] 모델 로드: {_MODEL_ID} on {_DEVICE}")
    _proc  = AutoProcessor.from_pretrained(_MODEL_ID)
    _model = AutoModel.from_pretrained(
        _MODEL_ID,
        torch_dtype=torch.float16 if _DEVICE == "cuda" else torch.float32,
    ).to(_DEVICE).eval()


@torch.inference_mode()
def embed_images(paths: list[Path]) -> np.ndarray:
    """(N, 1152) L2-normalized float32."""
    _load()
    out: list[np.ndarray] = []
    for i in range(0, len(paths), _BATCH):
        batch = [Image.open(p).convert("RGB") for p in paths[i:i+_BATCH]]
        inp = _proc(images=batch, return_tensors="pt").to(_DEVICE)
        vec = _model.get_image_features(**inp)
        vec = torch.nn.functional.normalize(vec, dim=-1)
        out.append(vec.cpu().float().numpy())
        if _DEVICE == "cuda":
            torch.cuda.empty_cache()
    return np.vstack(out).astype(np.float32)


@torch.inference_mode()
def embed_texts(texts: list[str]) -> np.ndarray:
    """쿼리 또는 캡션을 SigLIP2 text encoder 로 임베딩."""
    _load()
    out: list[np.ndarray] = []
    B = TRICHEF_CFG["BATCH_TXT"]
    for i in range(0, len(texts), B):
        inp = _proc(text=texts[i:i+B], padding="max_length",
                    truncation=True, return_tensors="pt").to(_DEVICE)
        vec = _model.get_text_features(**inp)
        vec = torch.nn.functional.normalize(vec, dim=-1)
        out.append(vec.cpu().float().numpy())
    return np.vstack(out).astype(np.float32)
