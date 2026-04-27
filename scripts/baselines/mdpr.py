"""scripts/baselines/mdpr.py — mDPR (castorini/mdpr-tied-pft-msmarco) baseline.

HuggingFace 모델: castorini/mdpr-tied-pft-msmarco
DPR 계열 bi-encoder (query-encoder + passage-encoder).

의존성: transformers>=4.30, torch, (faiss-cpu 또는 numpy fallback)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import torch

logger = logging.getLogger(__name__)

_MODEL_ID = "castorini/mdpr-tied-pft-msmarco"
_MAX_LENGTH_PASSAGE = 512
_MAX_LENGTH_QUERY = 128


class MDPRRetriever:
    """mDPR bi-encoder retriever.

    castorini/mdpr-tied-pft-msmarco 는 query / passage encoder 가
    동일 가중치(tied)이며 DPRQuestionEncoder / DPRContextEncoder API 를 공유.
    """

    def __init__(
        self,
        model_id: str = _MODEL_ID,
        device: Optional[str] = None,
        batch_size: int = 64,
    ) -> None:
        self.batch_size = batch_size
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"mDPR 모델 로드: {model_id} ({self.device})")

        try:
            from transformers import (  # type: ignore
                DPRContextEncoder,
                DPRContextEncoderTokenizerFast,
                DPRQuestionEncoder,
                DPRQuestionEncoderTokenizerFast,
            )
        except ImportError:
            raise ImportError(
                "transformers 패키지가 필요합니다.\n"
                "  pip install transformers>=4.30"
            )

        try:
            self._q_tokenizer = DPRQuestionEncoderTokenizerFast.from_pretrained(
                model_id
            )
            self._q_encoder = DPRQuestionEncoder.from_pretrained(model_id).to(
                self.device
            )
            self._q_encoder.eval()

            self._p_tokenizer = DPRContextEncoderTokenizerFast.from_pretrained(
                model_id
            )
            self._p_encoder = DPRContextEncoder.from_pretrained(model_id).to(
                self.device
            )
            self._p_encoder.eval()
        except Exception as exc:
            logger.error(f"mDPR 모델 로드 실패: {exc}")
            raise

        logger.info("mDPR 로드 완료")

    @torch.inference_mode()
    def _encode(
        self,
        texts: list[str],
        tokenizer,
        encoder,
        max_length: int,
    ) -> np.ndarray:
        """배치 인코딩 후 pooler_output 반환. (N, d) float32."""
        all_vecs: list[np.ndarray] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            enc = tokenizer(
                batch,
                max_length=max_length,
                truncation=True,
                padding=True,
                return_tensors="pt",
            ).to(self.device)
            output = encoder(**enc)
            # DPR pooler_output: (B, d)
            vecs = output.pooler_output.cpu().float().numpy()
            all_vecs.append(vecs)
        mat = np.concatenate(all_vecs, axis=0)
        # L2 normalize
        norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12
        return (mat / norms).astype(np.float32)

    def encode_passages(self, passages: list[str]) -> np.ndarray:
        """패시지 배치 인코딩. (N, d) float32."""
        return self._encode(
            passages,
            self._p_tokenizer,
            self._p_encoder,
            max_length=_MAX_LENGTH_PASSAGE,
        )

    def encode_query(self, query: str) -> np.ndarray:
        """쿼리 1건 인코딩. (d,) float32."""
        vecs = self._encode(
            [query],
            self._q_tokenizer,
            self._q_encoder,
            max_length=_MAX_LENGTH_QUERY,
        )
        return vecs[0]

    def search(
        self,
        query_vec: np.ndarray,
        passage_mat: np.ndarray,
        top_k: int = 100,
    ) -> list[tuple[int, float]]:
        """내적(dot product) 기반 top-k 검색."""
        from scripts.eval_miracl_ko import faiss_search  # type: ignore

        return faiss_search(query_vec, passage_mat, top_k=top_k)


# ── 외부 진입점 ────────────────────────────────────────────────────────────────


def get_retriever(
    model_id: str = _MODEL_ID,
    device: Optional[str] = None,
    batch_size: int = 64,
) -> MDPRRetriever:
    """eval_miracl_ko.py 가 호출하는 표준 진입점."""
    return MDPRRetriever(model_id=model_id, device=device, batch_size=batch_size)
