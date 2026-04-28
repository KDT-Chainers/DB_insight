"""embedders/trichef/bgem3_caption_im.py — BGE-M3 Dense Im 축 (v2 P1).

e5-large 대체. 한국어↔영어 크로스링구얼 정렬 및 장문(8192 tokens) 대응.
FlagEmbedding/sentence_transformers 미사용 — transformers 직접 호출로 siglip2_re 충돌 방지.
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
_lock     = threading.Lock()
_model    = None
_tok      = None


def _load():
    global _model, _tok
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        logger.info(f"[bgem3] 모델 로드: {_MODEL_ID} ({_DEVICE})")
        from transformers import AutoTokenizer, AutoModel
        _tok   = AutoTokenizer.from_pretrained(_MODEL_ID)
        dtype  = torch.float16 if _DEVICE == "cuda" else torch.float32
        _model = AutoModel.from_pretrained(_MODEL_ID, torch_dtype=dtype).to(_DEVICE)
        _model.eval()
        logger.info("[bgem3] 로드 완료")


def _mean_pool(last_hidden: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    mask = attention_mask.unsqueeze(-1).expand(last_hidden.size()).float()
    return torch.sum(last_hidden * mask, dim=1) / torch.clamp(mask.sum(dim=1), min=1e-9)


@torch.inference_mode()
def _encode(texts: list[str], max_length: int, batch_size: int) -> np.ndarray:
    _load()
    all_vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        enc = _tok(
            batch,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        ).to(_DEVICE)
        out  = _model(**enc)
        vecs = _mean_pool(out.last_hidden_state, enc["attention_mask"])
        vecs = torch.nn.functional.normalize(vecs, p=2, dim=-1)
        all_vecs.append(vecs.cpu().float().numpy())
    return np.vstack(all_vecs) if all_vecs else np.zeros((0, TRICHEF_CFG["DIM_IM"]), dtype=np.float32)


def embed_passage(texts: list[str], batch_size: int = 32,
                  max_length: int = 1024) -> np.ndarray:
    """장문 캡션(BLIP L3) 대응. (N, 1024) float32."""
    if not texts:
        return np.zeros((0, TRICHEF_CFG["DIM_IM"]), dtype=np.float32)
    return _encode(texts, max_length=max_length, batch_size=batch_size)


def embed_query(texts, max_length: int = 256) -> np.ndarray:
    """쿼리 임베딩. BGE-M3는 prefix 불필요. str/list[str] 모두 허용."""
    if isinstance(texts, str):
        texts = [texts]
    if not texts:
        return np.zeros((0, TRICHEF_CFG["DIM_IM"]), dtype=np.float32)
    return _encode(list(texts), max_length=max_length, batch_size=min(32, len(texts)))
