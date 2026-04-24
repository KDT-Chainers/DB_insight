"""DI_TriCHEF/captioner/qwen_vl_ko.py

Qwen2-VL-2B-Instruct 기반 한국어 이미지 캡셔너 (BLIP 대체).

목적: 영어 BLIP 캡션(자주 환각 + KR 쿼리 vocab 매칭 불가) 해결.
권장 환경: 로컬 GPU 8GB+ / Flash-Attn 2 선택.

양자화 옵션 (quantize 파라미터):
  "none"  : FP16/BF16 원본 (~4.5 GB VRAM) — 품질 최고
  "nf4"   : INT4 NF4 (BitsAndBytes) (~1.2 GB) — 권장, 품질 손실 < 2%
  "int8"  : INT8 (BitsAndBytes) (~2.2 GB) — 중간 절충

사용:
    cap = QwenKoCaptioner(quantize="nf4")   # RTX 4070 8GB 환경 권장
    text = cap.caption(pil_image)           # -> "웃고 있는 강아지가 사람 품에 안겨 있다"

Lazy-load: 첫 caption 호출 시 모델 초기화. re-captioning 배치 러너에서 공유.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MODEL_ID = "Qwen/Qwen2-VL-2B-Instruct"
SYSTEM_PROMPT = (
    "당신은 한국어 이미지 캡션 생성기입니다. "
    "반드시 한국어(한글)로만 답변하세요. "
    "중국어, 영어, 일본어, 한자는 절대 사용하지 마세요. "
    "이미지에 보이지 않는 장소·국가·수치는 추측하지 마세요."
)
DEFAULT_PROMPT = (
    "이 이미지를 한국어 한 문장(40자 이내)으로 설명하세요. "
    "보이는 사물과 장면만 기술하세요."
)


class QwenKoCaptioner:
    def __init__(self, model_id: str = MODEL_ID, device: str | None = None,
                 dtype: str = "float16", quantize: str = "nf4"):
        """
        Args:
            quantize: "nf4" (권장, ~1.2GB) | "int8" (~2.2GB) | "none" (~4.5GB FP16)
            dtype:    "float16" | "bfloat16" — quantize="none" 일 때만 직접 사용
        """
        self.model_id = model_id
        self.device = device
        self.dtype = dtype
        self.quantize = quantize
        self._model = None
        self._processor = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoProcessor, Qwen2VLForConditionalGeneration

        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")

        # ── 양자화 설정 ────────────────────────────────────────────────────────
        bnb_cfg = None
        if self.quantize in ("nf4", "int8") and device == "cuda":
            try:
                from transformers import BitsAndBytesConfig
                if self.quantize == "nf4":
                    bnb_cfg = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_use_double_quant=True,   # 추가 압축 (~0.5GB 추가 절감)
                        bnb_4bit_compute_dtype=torch.float16,
                    )
                    logger.info(f"[QwenKoCaptioner] NF4 INT4 양자화 적용 (~1.2GB VRAM)")
                else:  # int8
                    bnb_cfg = BitsAndBytesConfig(load_in_8bit=True)
                    logger.info(f"[QwenKoCaptioner] INT8 양자화 적용 (~2.2GB VRAM)")
            except ImportError:
                logger.warning("[QwenKoCaptioner] bitsandbytes 없음 — FP16 fallback")

        torch_dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16,
                       "float32": torch.float32}.get(self.dtype, torch.float16)

        logger.info(f"[QwenKoCaptioner] loading {self.model_id} on {device} "
                    f"(quantize={self.quantize}, dtype={self.dtype})")
        self._processor = AutoProcessor.from_pretrained(self.model_id)

        load_kwargs: dict = {"device_map": "auto" if bnb_cfg else device}
        if bnb_cfg:
            load_kwargs["quantization_config"] = bnb_cfg
        else:
            load_kwargs["torch_dtype"] = torch_dtype

        self._model = Qwen2VLForConditionalGeneration.from_pretrained(
            self.model_id, **load_kwargs,
        )
        self._model.eval()
        self._device = device

    @staticmethod
    def _build_messages(prompt: str) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": prompt},
                ],
            },
        ]

    @staticmethod
    def _resize(image: Any, max_side: int = 896) -> Any:
        """Qwen2-VL 은 입력 해상도에 따라 vision token 수가 선형 증가.
        고해상도 원본 사진(12MP+)은 토큰 수천개 → generate 극도로 느림.
        장변 max_side 로 축소하여 토큰 ≤ ~256 로 제한."""
        w, h = image.size
        m = max(w, h)
        if m <= max_side:
            return image
        scale = max_side / m
        return image.resize((int(w * scale), int(h * scale)))

    def caption(self, image: Any, prompt: str = DEFAULT_PROMPT,
                max_new_tokens: int = 60, max_image_side: int = 896) -> str:
        import torch

        self._load()
        image = self._resize(image, max_side=max_image_side)
        msgs = self._build_messages(prompt)
        text = self._processor.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=True,
        )
        inputs = self._processor(text=[text], images=[image],
                                 padding=True, return_tensors="pt").to(self._device)
        with torch.no_grad():
            out_ids = self._model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                repetition_penalty=1.3,
                no_repeat_ngram_size=3,
                early_stopping=True,
                num_beams=1,
            )
        trimmed = out_ids[:, inputs.input_ids.shape[1]:]
        decoded = self._processor.batch_decode(
            trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False,
        )
        return (decoded[0] if decoded else "").strip()

    def caption_batch(self, images: list[Any], prompt: str = DEFAULT_PROMPT,
                      max_new_tokens: int = 80) -> list[str]:
        return [self.caption(im, prompt, max_new_tokens) for im in images]
