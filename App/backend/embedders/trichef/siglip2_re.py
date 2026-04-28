"""embedders/trichef/siglip2_re.py — Re 축 (SigLIP2-SO400M 1152d).

이미지와 텍스트 양쪽을 동일 공간에 임베딩하여 cross-modal 코사인 유사도를 얻는다.

[양자화] INT8_RE_SIGLIP2=True 시 BitsAndBytes INT8 적용:
  FP16 ~1.0 GB → INT8 ~0.50 GB  (-0.50 GB)
  ViT 계열 임베딩 품질 변화 < 0.5% (dinov2_z.py 와 동일 패턴)
"""
from __future__ import annotations

import logging
import threading
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
_lock = threading.Lock()


def _load() -> None:
    global _model, _proc
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        _proc = AutoProcessor.from_pretrained(_MODEL_ID)
        use_int8 = TRICHEF_CFG.get("INT8_RE_SIGLIP2", False) and _DEVICE == "cuda"
        if use_int8:
            try:
                from transformers import BitsAndBytesConfig
                bnb_cfg = BitsAndBytesConfig(load_in_8bit=True)
                logger.info(f"[siglip2_re] INT8 양자화 로드: {_MODEL_ID} (~0.50 GB VRAM)")
                _model = AutoModel.from_pretrained(
                    _MODEL_ID, quantization_config=bnb_cfg, device_map="auto",
                ).eval()
            except ImportError:
                logger.warning("[siglip2_re] bitsandbytes 없음 — FP16 fallback")
                use_int8 = False
        if not use_int8:
            logger.info(f"[siglip2_re] FP16 로드: {_MODEL_ID} (~1.0 GB VRAM)")
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
        batch = []
        for p in paths[i:i+_BATCH]:
            with Image.open(p) as _img:
                batch.append(_img.convert("RGB"))
        inp = _proc(images=batch, return_tensors="pt").to(_DEVICE)
        vec = _model.get_image_features(**inp)
        if not isinstance(vec, torch.Tensor):
            vec = vec.pooler_output
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
        if not isinstance(vec, torch.Tensor):
            vec = vec.pooler_output
        vec = torch.nn.functional.normalize(vec, dim=-1)
        out.append(vec.cpu().float().numpy())
    return np.vstack(out).astype(np.float32)
