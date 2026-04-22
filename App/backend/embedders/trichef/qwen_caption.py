"""embedders/trichef/qwen_caption.py — Qwen2.5-VL-3B 로 이미지 캡션 + 쿼리 확장."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

from config import TRICHEF_CFG

logger = logging.getLogger(__name__)

_MODEL_ID = TRICHEF_CFG["MODEL_QWEN_VL"]
_DEVICE   = TRICHEF_CFG["DEVICE"]
_lock = threading.Lock()
_model = None
_proc  = None


def _load():
    global _model, _proc
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        logger.info(f"[qwen] 모델 로드: {_MODEL_ID}")
        _proc  = AutoProcessor.from_pretrained(_MODEL_ID)
        _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            _MODEL_ID,
            torch_dtype=torch.float16 if _DEVICE == "cuda" else torch.float32,
            device_map=_DEVICE,
        ).eval()


@torch.inference_mode()
def caption(image_path: Path, max_new: int = 64) -> str:
    _load()
    img = Image.open(image_path).convert("RGB")
    msg = [{"role": "user", "content": [
        {"type": "image", "image": img},
        {"type": "text",  "text": "이 이미지의 핵심 객체와 장면을 1문장으로 한국어 설명."},
    ]}]
    text = _proc.apply_chat_template(msg, tokenize=False, add_generation_prompt=True)
    inp = _proc(text=[text], images=[img], padding=True, return_tensors="pt").to(_DEVICE)
    out = _model.generate(**inp, max_new_tokens=max_new, do_sample=False)
    gen = _proc.batch_decode(out[:, inp.input_ids.shape[1]:],
                              skip_special_tokens=True)[0].strip()
    return gen


@torch.inference_mode()
def paraphrase(query: str, n: int = 3, max_new: int = 48) -> list[str]:
    _load()
    prompt = (
        f"다음 검색 쿼리를 의미가 같지만 표현이 다른 {n}개 문장으로 바꿔 한 줄씩 출력:\n"
        f"[쿼리] {query}"
    )
    msg = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
    text = _proc.apply_chat_template(msg, tokenize=False, add_generation_prompt=True)
    inp = _proc(text=[text], padding=True, return_tensors="pt").to(_DEVICE)
    out = _model.generate(**inp, max_new_tokens=max_new, do_sample=False)
    gen = _proc.batch_decode(out[:, inp.input_ids.shape[1]:],
                              skip_special_tokens=True)[0]
    lines = [l.strip("-•* ").strip() for l in gen.splitlines() if l.strip()]
    return [l for l in lines if l][:n]
