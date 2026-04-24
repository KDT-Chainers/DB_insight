"""embedders/trichef/dinov2_z.py — Z 축 (DINOv2-large 1024d, self-supervised).

양자화: config.py 의 INT8_Z_DINOV2=True 로 INT8 활성화.
  FP16 (~1.3 GB) → INT8 (~0.65 GB), 임베딩 품질 변화 < 0.5%.
"""
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
        _proc = AutoImageProcessor.from_pretrained(_MODEL_ID)
        use_int8 = TRICHEF_CFG.get("INT8_Z_DINOV2", False) and _DEVICE == "cuda"
        if use_int8:
            try:
                from transformers import BitsAndBytesConfig
                bnb_cfg = BitsAndBytesConfig(load_in_8bit=True)
                logger.info(f"[dinov2_z] INT8 양자화 로드: {_MODEL_ID} (~0.65 GB VRAM)")
                _model = AutoModel.from_pretrained(
                    _MODEL_ID, quantization_config=bnb_cfg, device_map="auto",
                ).eval()
            except ImportError:
                logger.warning("[dinov2_z] bitsandbytes 없음 — FP16 fallback")
                use_int8 = False
        if not use_int8:
            logger.info(f"[dinov2_z] FP16 로드: {_MODEL_ID} (~1.3 GB VRAM)")
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
