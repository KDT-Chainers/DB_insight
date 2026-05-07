"""scripts/baselines/bgem3.py — BGE-M3 (BAAI/bge-m3) baseline (Tri-CHEF Im 축).

기존 App/backend/embedders/trichef/bgem3_caption_im.py 의
embed_passage / embed_query 를 import 하여 Retriever Protocol 로 래핑.
Tri-CHEF 의 Im 축 sub-system 으로 라벨.

의존성: FlagEmbedding>=1.2 (App/backend requirements.txt 에 이미 포함)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# App/backend 를 sys.path 에 추가 (bgem3_caption_im 은 config 를 import)
_BACKEND_DIR = Path(__file__).resolve().parents[2] / "App" / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _import_bgem3():
    """bgem3_caption_im 을 lazy import. 실패 시 상세 안내."""
    try:
        import embedders.trichef.bgem3_caption_im as _mod  # type: ignore
        return _mod
    except ImportError as exc:
        raise ImportError(
            f"bgem3_caption_im import 실패: {exc}\n"
            f"  App/backend 경로: {_BACKEND_DIR}\n"
            "  FlagEmbedding 설치 여부 확인: pip install FlagEmbedding>=1.2"
        )
    except Exception as exc:
        raise RuntimeError(f"bgem3_caption_im 로드 오류: {exc}")


class BGEM3Retriever:
    """BGE-M3 Dense Im 축 Retriever.

    기존 bgem3_caption_im.embed_passage / embed_query 를 그대로 활용.
    BGE-M3 는 query prefix 불필요 (모델 내부 처리).
    """

    def __init__(self, batch_size: int = 32) -> None:
        self.batch_size = batch_size
        logger.info("BGE-M3 Im 축 Retriever 초기화 (lazy load)")
        self._mod = _import_bgem3()
        logger.info("bgem3_caption_im import 완료")

    def encode_passages(self, passages: list[str]) -> np.ndarray:
        """패시지 배치 인코딩. (N, 1024) float32 L2-normalized."""
        return self._mod.embed_passage(
            passages,
            batch_size=self.batch_size,
            max_length=1024,
        )

    def encode_query(self, query: str) -> np.ndarray:
        """쿼리 1건 인코딩. (1024,) float32 L2-normalized."""
        result = self._mod.embed_query(query, max_length=256)
        # embed_query 는 (N, d) 또는 (d,) 반환 가능 — 항상 1-d 로 squeeze
        arr = np.asarray(result, dtype=np.float32)
        return arr.reshape(-1) if arr.ndim == 2 else arr

    def search(
        self,
        query_vec: np.ndarray,
        passage_mat: np.ndarray,
        top_k: int = 100,
    ) -> list[tuple[int, float]]:
        """코사인 유사도(L2-norm 후 내적) top-k 검색."""
        # eval_miracl_ko 는 ROOT 기준으로 실행되므로 절대 import
        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from scripts.eval_miracl_ko import faiss_search  # type: ignore

        return faiss_search(query_vec, passage_mat, top_k=top_k)


# ── 외부 진입점 ────────────────────────────────────────────────────────────────


def get_retriever(batch_size: int = 32) -> BGEM3Retriever:
    """eval_miracl_ko.py 가 호출하는 표준 진입점."""
    return BGEM3Retriever(batch_size=batch_size)
