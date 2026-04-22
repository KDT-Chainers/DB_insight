"""services/trichef/unified_engine.py — 3 도메인 검색 통합 엔진.

Search flow: query → expand → 3축 쿼리 임베딩 → Hermitian → threshold → top-K.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from config import PATHS, TRICHEF_CFG
from embedders.trichef import siglip2_re
from embedders.trichef import bgem3_caption_im as e5_caption_im  # v2 P1: e5→BGE-M3 호환 alias
from services.trichef import calibration, qwen_expand, tri_gs

logger = logging.getLogger(__name__)


@dataclass
class TriChefResult:
    id: str
    score: float
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


class TriChefEngine:
    """3축 복소수 검색 엔진. 이미지/문서 양쪽 재사용 가능."""

    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._load_all()

    def _load_all(self) -> None:
        # 이미지
        idir = Path(PATHS["TRICHEF_IMG_CACHE"])
        if (idir / "cache_img_Re_siglip2.npy").exists():
            self._cache["image"] = {
                "Re":  np.load(idir / "cache_img_Re_siglip2.npy"),
                "Im":  np.load(idir / "cache_img_Im_e5cap.npy"),
                "Z":   np.load(idir / "cache_img_Z_dinov2.npy"),
                "ids": json.loads(
                    (idir / "img_ids.json").read_text(encoding="utf-8")
                )["ids"],
            }
        # 문서 페이지
        ddir = Path(PATHS["TRICHEF_DOC_CACHE"])
        if (ddir / "cache_doc_page_Re.npy").exists():
            self._cache["doc_page"] = {
                "Re":  np.load(ddir / "cache_doc_page_Re.npy"),
                "Im":  np.load(ddir / "cache_doc_page_Im.npy"),
                "Z":   np.load(ddir / "cache_doc_page_Z.npy"),
                "ids": json.loads(
                    (ddir / "doc_page_ids.json").read_text(encoding="utf-8")
                )["ids"],
            }
        logger.info(f"[engine] 캐시 로드 완료: {list(self._cache.keys())}")

    def _embed_query(self, query: str) -> tuple[np.ndarray, np.ndarray]:
        variants = qwen_expand.expand(query)
        q_Re = qwen_expand.avg_normalize(siglip2_re.embed_texts(variants))
        q_Im = qwen_expand.avg_normalize(e5_caption_im.embed_query(variants))
        return q_Re, q_Im

    def search(self, query: str, domain: str, topk: int = 20) -> list[TriChefResult]:
        if domain not in self._cache:
            logger.warning(f"[engine] 도메인 {domain} 캐시 없음")
            return []
        q_Re, q_Im = self._embed_query(query)
        d = self._cache[domain]
        # Z 쿼리: DINOv2 는 text encoder 없음 → Im 으로 근사
        q_Z = q_Im
        scores = tri_gs.hermitian_score(
            q_Re[None, :], q_Im[None, :], q_Z[None, :],
            d["Re"], d["Im"], d["Z"],
        )[0]  # (N,)
        cal = calibration.get_thresholds(domain)
        abs_thr = cal["abs_threshold"]
        mu, sig = cal["mu_null"], cal["sigma_null"]
        order = np.argsort(-scores)
        out: list[TriChefResult] = []
        for i in order[: topk * 2]:
            s = float(scores[i])
            if s < abs_thr:
                continue
            z = (s - mu) / max(sig, 1e-9)
            conf = 0.5 * (1 + _erf(z / (2 ** 0.5)))
            out.append(TriChefResult(
                id=d["ids"][i], score=s, confidence=conf,
                metadata={"domain": domain},
            ))
            if len(out) >= topk:
                break
        return out

    def reload(self) -> None:
        """캐시 재로드 (재임베딩 후 호출)."""
        self._cache.clear()
        self._load_all()


def _erf(x: float) -> float:
    # Abramowitz & Stegun 7.1.26
    import math
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    s = 1 if x >= 0 else -1
    x = abs(x)
    t = 1 / (1 + p * x)
    y = 1 - ((((a5*t + a4)*t + a3)*t + a2)*t + a1)*t * math.exp(-x * x)
    return s * y
