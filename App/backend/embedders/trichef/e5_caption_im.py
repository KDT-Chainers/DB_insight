"""embedders/trichef/e5_caption_im.py — Im 축 (multilingual-e5-large 1024d).

이미지/문서 페이지의 캡션 텍스트를 e5 로 임베딩하여 Im 축으로 사용.
"""
from __future__ import annotations

import logging

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from config import TRICHEF_CFG

logger = logging.getLogger(__name__)

_MODEL_ID = TRICHEF_CFG["MODEL_IM_E5LARGE"]
_DEVICE   = TRICHEF_CFG["DEVICE"]

_tok = None
_model = None


def _load():
    global _tok, _model
    if _model is not None:
        return
    logger.info(f"[e5_im] 모델 로드: {_MODEL_ID}")
    _tok   = AutoTokenizer.from_pretrained(_MODEL_ID)
    _model = AutoModel.from_pretrained(
        _MODEL_ID,
        torch_dtype=torch.float16 if _DEVICE == "cuda" else torch.float32,
    ).to(_DEVICE).eval()


def _encode(texts: list[str], prefix: str) -> np.ndarray:
    _load()
    B = TRICHEF_CFG["BATCH_TXT"]
    out: list[np.ndarray] = []
    for i in range(0, len(texts), B):
        batch = [f"{prefix}: {t}" for t in texts[i:i+B]]
        inp = _tok(batch, padding=True, truncation=True,
                   max_length=512, return_tensors="pt").to(_DEVICE)
        with torch.inference_mode():
            hid = _model(**inp).last_hidden_state
            mask = inp["attention_mask"].unsqueeze(-1).float()
            emb = (hid * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            emb = torch.nn.functional.normalize(emb, dim=-1)
        out.append(emb.cpu().float().numpy())
    return np.vstack(out).astype(np.float32)


def embed_passage(texts: list[str]) -> np.ndarray:
    return _encode(texts, "passage")


def embed_query(texts: list[str]) -> np.ndarray:
    return _encode(texts, "query")
