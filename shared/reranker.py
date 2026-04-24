"""shared/reranker.py — BGE-reranker-v2-m3 cross-encoder 공유 래퍼.

DI/MR 양쪽에서 import 해서 top-K 재순위화에 사용.

사용:
    from shared.reranker import BgeRerankerV2
    r = BgeRerankerV2()
    scores = r.score(query, passages)     # np.ndarray (N,)

모델: BAAI/bge-reranker-v2-m3  (~560MB, CPU/GPU 자동, bf16/fp16)
Lazy-load: 첫 score 호출 시 초기화.

성능:
  · 100 passage / CPU: ~4s
  · 100 passage / GPU bf16: ~0.3s
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"


class BgeRerankerV2:
    def __init__(self, model_id: str = DEFAULT_MODEL, device: str | None = None,
                 dtype: str = "bfloat16", max_length: int = 512):
        self.model_id = model_id
        self.device = device
        self.dtype = dtype
        self.max_length = max_length
        self._model = None
        self._tok = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        torch_dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16,
                       "float32": torch.float32}.get(self.dtype, torch.bfloat16)
        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"[Reranker] loading {self.model_id} on {device} ({self.dtype})")
        self._tok = AutoTokenizer.from_pretrained(self.model_id)
        self._model = AutoModelForSequenceClassification.from_pretrained(
            self.model_id, torch_dtype=torch_dtype,
        ).to(device).eval()
        self._device = device

    def score(self, query: str, passages: list[str],
              batch_size: int = 32) -> np.ndarray:
        """쿼리-패시지 쌍별 relevance score. 높을수록 관련."""
        import torch

        if not passages:
            return np.zeros(0, dtype=np.float32)
        self._load()

        all_scores: list[float] = []
        for i in range(0, len(passages), batch_size):
            chunk = passages[i:i + batch_size]
            pairs = [[query, p] for p in chunk]
            enc = self._tok(pairs, padding=True, truncation=True,
                            max_length=self.max_length,
                            return_tensors="pt").to(self._device)
            with torch.no_grad():
                logits = self._model(**enc).logits.view(-1).float().cpu().numpy()
            all_scores.extend(logits.tolist())
        return np.asarray(all_scores, dtype=np.float32)

    def rerank(self, query: str, items: list[dict[str, Any]],
               text_key: str = "text", top_k: int | None = None,
               score_key: str = "rerank_score") -> list[dict[str, Any]]:
        """items 리스트에 rerank_score 주입 후 내림차순 정렬하여 반환."""
        if not items:
            return items
        texts = [str(it.get(text_key, "")) for it in items]
        scores = self.score(query, texts)
        for it, s in zip(items, scores):
            it[score_key] = float(s)
        items = sorted(items, key=lambda x: x.get(score_key, 0.0), reverse=True)
        return items[:top_k] if top_k else items


_singleton: BgeRerankerV2 | None = None


def get_reranker() -> BgeRerankerV2:
    """프로세스 전역 싱글턴 — 모델 중복 로드 방지."""
    global _singleton
    if _singleton is None:
        _singleton = BgeRerankerV2()
    return _singleton
