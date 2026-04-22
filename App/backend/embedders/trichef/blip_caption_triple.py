"""embedders/trichef/blip_caption_triple.py — BLIP 3단계 캡션 (v2 P1).

L1: 짧은 설명 (1문장, ~15 단어)     — 렉시컬 시드
L2: 키워드 (쉼표 구분, 5~10개)      — BM25 + auto_vocab 소스
L3: 상세 설명 (30~60 단어 1문단)    — BGE-M3 Im 축 입력

qwen_caption.py 단일 BLIP 캡션과 분리. 기존 호환성을 위해 caption()은 L1 동작.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, asdict
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


@dataclass
class Caption3:
    L1: str   # short
    L2: str   # keywords (comma-separated)
    L3: str   # description

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "Caption3":
        d = json.loads(s)
        return cls(L1=d.get("L1", ""), L2=d.get("L2", ""), L3=d.get("L3", ""))


def _load():
    global _model, _proc
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        logger.info(f"[blip3] 모델 로드: {_MODEL_ID} ({_DEVICE})")
        _proc  = BlipProcessor.from_pretrained(_MODEL_ID)
        dtype  = torch.float16 if _DEVICE == "cuda" else torch.float32
        _model = BlipForConditionalGeneration.from_pretrained(
            _MODEL_ID, torch_dtype=dtype,
        ).to(_DEVICE).eval()
        logger.info("[blip3] 로드 완료")


def _gen(img: Image.Image, prompt: str, max_new: int) -> str:
    inp = _proc(images=img, text=prompt, return_tensors="pt").to(_DEVICE)
    if _DEVICE == "cuda":
        inp = {k: (v.half() if v.dtype == torch.float32 else v) for k, v in inp.items()}
    out = _model.generate(**inp, max_new_tokens=max_new, num_beams=3)
    txt = _proc.decode(out[0], skip_special_tokens=True).strip()
    if prompt and txt.startswith(prompt):
        txt = txt[len(prompt):].strip()
    return txt


@torch.inference_mode()
def caption_triple(image_path: Path) -> Caption3:
    """BLIP 은 단일 생성기이므로 prompt 로 3 가지 출력 유도."""
    _load()
    img = Image.open(image_path).convert("RGB")
    l1 = _gen(img, "",                                    max_new=30)
    l2_raw = _gen(img, "a photo showing",                 max_new=40)
    l3 = _gen(img, "a detailed description of the image:", max_new=96)
    keywords = _extract_keywords(l2_raw + " " + l3)
    return Caption3(L1=l1, L2=keywords, L3=l3 or l1)


def _extract_keywords(text: str, top: int = 10) -> str:
    """간단 키워드 추출: 명사 후보 단어 빈도 상위."""
    STOP = {
        "a","an","the","of","in","on","at","with","and","or","is","are",
        "this","that","it","to","for","by","as","from","be","was","were",
        "has","have","had","showing","photo","image","picture"
    }
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w in STOP: continue
        freq[w] = freq.get(w, 0) + 1
    kws = sorted(freq, key=lambda x: -freq[x])[:top]
    return ", ".join(kws)


# 기존 단일 캡션 API 호환
@torch.inference_mode()
def caption(image_path: Path, max_new: int = 48) -> str:
    return caption_triple(image_path).L1
