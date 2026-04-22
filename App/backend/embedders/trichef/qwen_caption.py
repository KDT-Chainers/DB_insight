"""embedders/trichef/qwen_caption.py — BLIP-base 이미지 캡션 (v1 안정화).

8GB VRAM 환경에서 Qwen2.5-VL-3B는 shared memory offload로 실사용 불가.
v1 베이스라인에서는 BLIP-base(Salesforce)로 교체 — 영어 캡션이지만 Im축
e5-large(multilingual)가 크로스링구얼 정렬을 제공하므로 한국어 쿼리도 지원.

v2(P1)에서 BLIP 3단계(caption/keywords/description)로 확장 예정.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import torch
from PIL import Image
from transformers import BlipProcessor, BlipForConditionalGeneration

from config import TRICHEF_CFG

logger = logging.getLogger(__name__)

_MODEL_ID = "Salesforce/blip-image-captioning-base"
_DEVICE   = TRICHEF_CFG["DEVICE"]
_lock = threading.Lock()
_model: BlipForConditionalGeneration | None = None
_proc:  BlipProcessor | None = None


def _load():
    global _model, _proc
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        logger.info(f"[blip] 모델 로드: {_MODEL_ID} ({_DEVICE})")
        _proc  = BlipProcessor.from_pretrained(_MODEL_ID)
        dtype  = torch.float16 if _DEVICE == "cuda" else torch.float32
        _model = BlipForConditionalGeneration.from_pretrained(
            _MODEL_ID, torch_dtype=dtype,
        ).to(_DEVICE).eval()
        logger.info("[blip] 로드 완료")


@torch.inference_mode()
def caption(image_path: Path, max_new: int = 48) -> str:
    _load()
    img = Image.open(image_path).convert("RGB")
    inp = _proc(images=img, return_tensors="pt").to(_DEVICE)
    if _DEVICE == "cuda":
        inp = {k: (v.half() if v.dtype == torch.float32 else v) for k, v in inp.items()}
    out = _model.generate(**inp, max_new_tokens=max_new, num_beams=3)
    return _proc.decode(out[0], skip_special_tokens=True).strip()


@torch.inference_mode()
def paraphrase(query: str, n: int = 3, max_new: int = 48) -> list[str]:
    """v1: paraphrase 비활성 — 원쿼리만 반환."""
    return [query]
