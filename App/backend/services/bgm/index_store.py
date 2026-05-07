"""FAISS IndexFlatIP + meta JSON 저장/조회.

embedding 행 i ↔ meta[i] ↔ filename. 인덱스 일관성은 호출 측 책임.

faiss 미설치 시 numpy fallback (102곡 규모면 충분).
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _try_faiss():
    try:
        import faiss  # type: ignore
        return faiss
    except ImportError:
        return None


def build_index(emb: np.ndarray):
    """L2-normalized (N, D) → faiss IndexFlatIP 또는 numpy ndarray fallback."""
    if emb.ndim != 2:
        raise ValueError(f"emb는 2D, 받은 shape={emb.shape}")
    emb = emb.astype(np.float32, copy=False)

    faiss = _try_faiss()
    if faiss is None:
        logger.info("[bgm.index] faiss 미설치 — numpy fallback 사용")
        return emb  # ndarray 자체를 인덱스로 사용

    idx = faiss.IndexFlatIP(emb.shape[1])
    idx.add(emb)
    return idx


def save_index(index, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    faiss = _try_faiss()
    if faiss is not None and not isinstance(index, np.ndarray):
        faiss.write_index(index, str(p))
    else:
        # numpy fallback: .npy 로 저장
        np.save(str(p) + ".npy", index)


def load_index(path: str | Path):
    p = Path(path)
    faiss = _try_faiss()
    if faiss is not None and p.is_file():
        try:
            return faiss.read_index(str(p))
        except Exception as e:
            logger.warning(f"[bgm.index] faiss 로드 실패: {e}")
    np_path = Path(str(p) + ".npy")
    if np_path.is_file():
        return np.load(str(np_path))
    return None


def search(index, query: np.ndarray, top_k: int) -> tuple[np.ndarray, np.ndarray]:
    """query (D,) 또는 (1, D) → (scores [top_k], indices [top_k]).
    L2-normalized 기준 inner product (= cosine)."""
    if query.ndim == 1:
        query = query[None, :]
    query = query.astype(np.float32, copy=False)

    faiss = _try_faiss()
    if faiss is not None and not isinstance(index, np.ndarray):
        scores, idxs = index.search(query, top_k)
        return scores[0], idxs[0]

    # numpy fallback
    sims = (index @ query.T).reshape(-1)
    n = sims.shape[0]
    k = min(top_k, n)
    if k == 0:
        return np.zeros(0, dtype=np.float32), np.zeros(0, dtype=np.int64)
    order = np.argsort(-sims)[:k]
    return sims[order].astype(np.float32), order.astype(np.int64)


# ── Meta Store ───────────────────────────────────────────────────────────────

class MetaStore:
    """audio_meta.json 단순 CRUD 래퍼.

    각 항목 스키마:
      {
        "filename":        "Artist_Title.mp4",
        "path":            "<absolute>",
        "guess_artist":    "Artist",
        "guess_title":     "Title",
        "duration":        187.4,
        "acr_artist":      "" | "...",
        "acr_title":       "" | "...",
        "acr_synced_at":   null | "ISO-8601",
        "tags":            ["calm", "fast", ...],
        "params":          {"tempo_bpm": 120.0, ...},   # librosa flat
      }
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._items: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.load()

    def load(self) -> None:
        if self.path.is_file():
            try:
                self._items = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"[bgm.meta] 파싱 실패, 빈 상태로 시작: {e}")
                self._items = []
        else:
            self._items = []

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._items, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def all(self) -> list[dict[str, Any]]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def replace_all(self, items: list[dict[str, Any]]) -> None:
        with self._lock:
            self._items = list(items)
        self.save()

    def update_by_filename(self, filename: str, patch: dict[str, Any]) -> bool:
        with self._lock:
            for it in self._items:
                if it.get("filename") == filename:
                    it.update(patch)
                    self.save()
                    return True
        return False

    def find_index(self, filename: str) -> int:
        for i, it in enumerate(self._items):
            if it.get("filename") == filename:
                return i
        return -1
