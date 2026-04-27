"""scripts/baselines/mcontriever.py — mContriever (facebook/mcontriever-msmarco) baseline.

HuggingFace 모델: facebook/mcontriever-msmarco (또는 facebook/mcontriever)
Shared encoder (q/p 동일), mean pooling.

의존성: transformers>=4.30, torch, (faiss-cpu 또는 numpy fallback)
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)

_MODEL_ID_PRIMARY = "facebook/mcontriever-msmarco"
_MODEL_ID_FALLBACK = "facebook/mcontriever"
_MAX_LENGTH = 512


def _mean_pool(
    token_embeddings: torch.Tensor,
    attention_mask: torch.Tensor,
) -> torch.Tensor:
    """Contriever 스타일 mean pooling (패딩 토큰 제외)."""
    mask_expanded = attention_mask.unsqueeze(-1).float()
    summed = (token_embeddings * mask_expanded).sum(dim=1)
    counts = mask_expanded.sum(dim=1).clamp(min=1e-9)
    return summed / counts


class MContrieverRetriever:
    """mContriever shared encoder retriever.

    query 와 passage 를 동일한 encoder 로 인코딩.
    mean pooling 후 L2 normalize.
    """

    def __init__(
        self,
        model_id: str = _MODEL_ID_PRIMARY,
        device: Optional[str] = None,
        batch_size: int = 64,
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

        # primary → fallback 순서로 시도
        loaded = False
        for mid in (model_id, _MODEL_ID_FALLBACK):
            try:
                logger.info(f"mContriever 모델 로드 시도: {mid} ({self.device})")
                self._tokenizer = AutoTokenizer.from_pretrained(mid)
                self._model = AutoModel.from_pretrained(mid).to(self.device)
                self._model.eval()
                self.model_id = mid
                loaded = True
                logger.info(f"mContriever 로드 완료: {mid}")
                break
            except Exception as exc:
                logger.warning(f"{mid} 로드 실패: {exc}")

        if not loaded:
            raise RuntimeError(
                f"mContriever 모델 로드 실패 "
                f"({_MODEL_ID_PRIMARY}, {_MODEL_ID_FALLBACK} 모두 실패)"
            )

    @torch.inference_mode()
    def _encode(self, texts: list[str], max_length: int = _MAX_LENGTH) -> np.ndarray:
        """배치 mean-pool 인코딩. (N, d) float32 L2-normalized."""
        all_vecs: list[np.ndarray] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            enc = self._tokenizer(
                batch,
                max_length=max_length,
                truncation=True,
                padding=True,
                return_tensors="pt",
            ).to(self.device)
            outputs = self._model(**enc)
            # last_hidden_state: (B, T, d)
            pooled = _mean_pool(outputs.last_hidden_state, enc["attention_mask"])
            pooled = F.normalize(pooled, p=2, dim=-1)
            all_vecs.append(pooled.cpu().float().numpy())
        return np.concatenate(all_vecs, axis=0).astype(np.float32)

    def encode_passages(self, passages: list[str]) -> np.ndarray:
        """패시지 배치 인코딩. (N, d) float32."""
        return self._encode(passages)

    def encode_query(self, query: str) -> np.ndarray:
        """쿼리 1건 인코딩. (d,) float32."""
        return self._encode([query])[0]

    def search(
        self,
        query_vec: np.ndarray,
        passage_mat: np.ndarray,
        top_k: int = 100,
    ) -> list[tuple[int, float]]:
        """코사인 유사도(L2-norm 후 내적) top-k 검색."""
        from scripts.eval_miracl_ko import faiss_search  # type: ignore

        return faiss_search(query_vec, passage_mat, top_k=top_k)


# ── 외부 진입점 ────────────────────────────────────────────────────────────────


def get_retriever(
    model_id: str = _MODEL_ID_PRIMARY,
    device: Optional[str] = None,
    batch_size: int = 64,
) -> MContrieverRetriever:
    """eval_miracl_ko.py 가 호출하는 표준 진입점."""
    return MContrieverRetriever(model_id=model_id, device=device, batch_size=batch_size)
