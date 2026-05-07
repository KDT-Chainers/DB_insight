"""scripts/baselines/me5.py — Multilingual-E5 (intfloat/multilingual-e5-large) baseline.

HuggingFace 모델: intfloat/multilingual-e5-large (또는 multilingual-e5-large-instruct)
E5 prefix: query → "query: ...", passage → "passage: ..."
mean pooling + L2 normalize.

의존성: transformers>=4.30, torch, sentence-transformers (optional)
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)

_MODEL_ID_PRIMARY = "intfloat/multilingual-e5-large"
_MODEL_ID_FALLBACK = "intfloat/multilingual-e5-base"
_MAX_LENGTH = 512
_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "


def _mean_pool(
    token_embeddings: torch.Tensor,
    attention_mask: torch.Tensor,
) -> torch.Tensor:
    """E5 스타일 mean pooling."""
    mask_expanded = attention_mask.unsqueeze(-1).float()
    summed = (token_embeddings * mask_expanded).sum(dim=1)
    counts = mask_expanded.sum(dim=1).clamp(min=1e-9)
    return summed / counts


class ME5Retriever:
    """Multilingual-E5-large retriever.

    E5 prefix 규칙:
    - 쿼리: "query: {query}"
    - 패시지: "passage: {title} {text}"
    mean pooling 후 L2 normalize.
    """

    def __init__(
        self,
        model_id: str = _MODEL_ID_PRIMARY,
        device: Optional[str] = None,
        batch_size: int = 32,
    ) -> None:
        self.batch_size = batch_size
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        try:
            from transformers import AutoModel, AutoTokenizer  # type: ignore
        except ImportError:
            raise ImportError(
                "transformers 패키지가 필요합니다.\n"
                "  pip install transformers>=4.30"
            )

        loaded = False
        for mid in (model_id, _MODEL_ID_FALLBACK):
            try:
                logger.info(f"ME5 모델 로드 시도: {mid} ({self.device})")
                self._tokenizer = AutoTokenizer.from_pretrained(mid)
                self._model = AutoModel.from_pretrained(mid).to(self.device)
                self._model.eval()
                self.model_id = mid
                loaded = True
                logger.info(f"ME5 로드 완료: {mid}")
                break
            except Exception as exc:
                logger.warning(f"{mid} 로드 실패: {exc}")

        if not loaded:
            raise RuntimeError(
                f"ME5 모델 로드 실패 "
                f"({_MODEL_ID_PRIMARY}, {_MODEL_ID_FALLBACK} 모두 실패)"
            )

    @torch.inference_mode()
    def _encode(self, texts: list[str]) -> np.ndarray:
        """배치 인코딩 (prefix 이미 적용된 텍스트). (N, d) float32 L2-normalized."""
        all_vecs: list[np.ndarray] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            enc = self._tokenizer(
                batch,
                max_length=_MAX_LENGTH,
                truncation=True,
                padding=True,
                return_tensors="pt",
            ).to(self.device)
            outputs = self._model(**enc)
            pooled = _mean_pool(outputs.last_hidden_state, enc["attention_mask"])
            pooled = F.normalize(pooled, p=2, dim=-1)
            all_vecs.append(pooled.cpu().float().numpy())
        return np.concatenate(all_vecs, axis=0).astype(np.float32)

    def encode_passages(self, passages: list[str]) -> np.ndarray:
        """E5 passage prefix 적용 후 배치 인코딩. (N, d) float32."""
        prefixed = [_PASSAGE_PREFIX + p for p in passages]
        return self._encode(prefixed)

    def encode_query(self, query: str) -> np.ndarray:
        """E5 query prefix 적용 후 1건 인코딩. (d,) float32."""
        prefixed = [_QUERY_PREFIX + query]
        return self._encode(prefixed)[0]

    def search(
        self,
        query_vec: np.ndarray,
        passage_mat: np.ndarray,
        top_k: int = 100,
    ) -> list[tuple[int, float]]:
        """코사인 유사도 top-k 검색 (L2-norm 후 내적)."""
        from scripts.eval_miracl_ko import faiss_search  # type: ignore

        return faiss_search(query_vec, passage_mat, top_k=top_k)


# ── 외부 진입점 ────────────────────────────────────────────────────────────────


def get_retriever(
    model_id: str = _MODEL_ID_PRIMARY,
    device: Optional[str] = None,
    batch_size: int = 32,
) -> ME5Retriever:
    """eval_miracl_ko.py 가 호출하는 표준 진입점."""
    return ME5Retriever(model_id=model_id, device=device, batch_size=batch_size)
