"""embedders/trichef/dinov2_z.py — Z 축 (DINOv2-large 1024d, self-supervised)."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel

from config import TRICHEF_CFG

logger = logging.getLogger(__name__)

_MODEL_ID = TRICHEF_CFG["MODEL_Z_DINOV2"]
_DEVICE   = TRICHEF_CFG["DEVICE"]
_BATCH    = TRICHEF_CFG["BATCH_IMG"]

_model = None
_proc  = None
_lock  = threading.Lock()


def _load():
    global _model, _proc
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        logger.info(f"[dinov2_z] 모델 로드: {_MODEL_ID}")
        _proc  = AutoImageProcessor.from_pretrained(_MODEL_ID)
        _model = AutoModel.from_pretrained(
            _MODEL_ID,
            torch_dtype=torch.float16 if _DEVICE == "cuda" else torch.float32,
        ).to(_DEVICE).eval()


@torch.inference_mode()
def embed_images(paths: list[Path]) -> np.ndarray:
    _load()
    out: list[np.ndarray] = []
    for i in range(0, len(paths), _BATCH):
        batch = []
        for p in paths[i:i+_BATCH]:
            with Image.open(p) as _img:
                batch.append(_img.convert("RGB"))
        inp = _proc(images=batch, return_tensors="pt").to(_DEVICE)
        out_d = _model(**inp)
        # [CLS] 토큰 (N, 1024)
        vec = out_d.last_hidden_state[:, 0]
        vec = torch.nn.functional.normalize(vec, dim=-1)
        out.append(vec.cpu().float().numpy())
        if _DEVICE == "cuda":
            torch.cuda.empty_cache()
    return np.vstack(out).astype(np.float32)
