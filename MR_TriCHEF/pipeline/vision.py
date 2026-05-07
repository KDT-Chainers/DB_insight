"""SigLIP2 (의미비전, Re축 + 쿼리 텍스트) + DINOv2 (구조비전, Z축)."""
from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from .paths import MODEL_SIGLIP2, MODEL_DINOV2


# ── SigLIP2 ────────────────────────────────────────────────────────────────
class SigLIP2Encoder:
    """이미지(Re축) + 쿼리 텍스트 임베딩 양방향 지원."""

    def __init__(self, model_id: str = MODEL_SIGLIP2, device: str = "cuda"):
        from transformers import AutoModel, AutoProcessor
        self.device = device
        # low_cpu_mem_usage=False: 신버전 transformers가 meta 텐서를 쓸 때 .to(device) 실패 방지
        self.model = AutoModel.from_pretrained(
            model_id, torch_dtype=torch.float16, low_cpu_mem_usage=False
        ).to(device).eval()
        self.proc  = AutoProcessor.from_pretrained(model_id)

    @torch.inference_mode()
    def embed_images(self, paths: list[Path], batch: int = 4) -> np.ndarray:
        vecs: list[np.ndarray] = []
        for i in range(0, len(paths), batch):
            imgs = [Image.open(p).convert("RGB") for p in paths[i:i+batch]]
            # naflex: 가변 해상도 → padding 필요
            inputs = self.proc(images=imgs, return_tensors="pt", padding=True).to(self.device)
            if "pixel_values" in inputs:
                inputs["pixel_values"] = inputs["pixel_values"].to(torch.float16)
            feats = self.model.get_image_features(**inputs)
            feats = torch.nn.functional.normalize(feats, dim=-1)
            vecs.append(feats.float().cpu().numpy())
        return np.vstack(vecs).astype(np.float32) if vecs else np.zeros((0, 1152), dtype=np.float32)

    @torch.inference_mode()
    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1152), dtype=np.float32)
        inputs = self.proc(text=texts, return_tensors="pt",
                           padding="max_length", truncation=True).to(self.device)
        feats = self.model.get_text_features(**inputs)
        feats = torch.nn.functional.normalize(feats, dim=-1)
        return feats.float().cpu().numpy().astype(np.float32)

    def unload(self):
        del self.model, self.proc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


# ── DINOv2 (구조비전, Z축) ─────────────────────────────────────────────────
class DINOv2Encoder:
    """DINOv2 base — 구조적(비의미) 비전 특징. Z축."""

    def __init__(self, model_id: str = MODEL_DINOV2, device: str = "cuda"):
        from transformers import AutoImageProcessor, AutoModel
        self.device = device
        self.proc  = AutoImageProcessor.from_pretrained(model_id)
        # low_cpu_mem_usage=False: 신버전 transformers meta 텐서 → .to(device) 충돌 방지
        self.model = AutoModel.from_pretrained(
            model_id, torch_dtype=torch.float16, low_cpu_mem_usage=False
        ).to(device).eval()

    @torch.inference_mode()
    def embed_images(self, paths: list[Path], batch: int = 4) -> np.ndarray:
        vecs: list[np.ndarray] = []
        dim = getattr(self.model.config, "hidden_size", 1024)
        for i in range(0, len(paths), batch):
            imgs = [Image.open(p).convert("RGB") for p in paths[i:i+batch]]
            inputs = self.proc(images=imgs, return_tensors="pt").to(self.device)
            inputs["pixel_values"] = inputs["pixel_values"].to(torch.float16)
            out = self.model(**inputs)
            # CLS 토큰 (첫 토큰) pooled feature — large=1024, base=768
            feats = out.last_hidden_state[:, 0, :]
            feats = torch.nn.functional.normalize(feats, dim=-1)
            vecs.append(feats.float().cpu().numpy())
        return np.vstack(vecs).astype(np.float32) if vecs else np.zeros((0, dim), dtype=np.float32)

    def unload(self):
        del self.model, self.proc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
