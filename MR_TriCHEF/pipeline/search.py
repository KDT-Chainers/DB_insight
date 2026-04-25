"""3축 Hermitian 검색 엔진 + ASF(한글 bigram IDF 오버랩) 결합.

Movie: A = q_sig · Re(1152),  B = q_bge · Im(1024),  C = 0 (쿼리 비전 없음)
       per_seg_dense = sqrt(A² + (0.4·B)²)
Music: A = q_sig · Re(1152 SigLIP2-text),  B = q_bge · Im(1024 BGE-M3)
       per_seg_dense = sqrt(A² + (0.4·B)²)  # Re축이 BGE-M3→SigLIP2로 전환됨

파일 집계: 세그먼트 top-3 평균 → 도메인 null calibration → z-score.
최종:      final = α·z_dense + β·lexical + γ·asf

사용자 쿼리는 한/영 혼합 전제 (Helsinki MT 제거). BGE-M3 다국어로 대응.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


# 도메인별 가중치: (α dense, β lexical, γ asf).  lexical 은 현재 미구현 → β=0.
WEIGHTS = {
    "movie": (0.75, 0.0, 0.25),
    "music": (0.75, 0.0, 0.25),
}


@dataclass
class SearchHit:
    file:       str
    file_name:  str
    score:      float
    confidence: float
    segments:   list[dict] = field(default_factory=list)


def _cos(q: np.ndarray, M: np.ndarray) -> np.ndarray:
    if M.size == 0 or q is None or q.size == 0:
        return np.zeros((M.shape[0],), dtype=np.float32)
    q = q.astype(np.float32)
    M = M.astype(np.float32)
    if q.ndim == 2:
        q = q[0]
    return M @ q


def _load_domain(cache_dir: Path, kind: str):
    def _npy(name: str):
        p = cache_dir / name
        return np.load(p) if p.exists() else np.zeros((0, 1), dtype=np.float32)

    Re = _npy(f"cache_{kind}_Re.npy")
    Im = _npy(f"cache_{kind}_Im.npy")
    Z  = _npy(f"cache_{kind}_Z.npy")
    ids_path  = cache_dir / f"{kind}_ids.json"
    segs_path = cache_dir / "segments.json"
    ids: list[str] = []
    if ids_path.exists():
        try:
            ids = json.loads(ids_path.read_text(encoding="utf-8")).get("ids", [])
        except Exception:
            ids = []
    segs: list[dict] = []
    if segs_path.exists():
        try:
            segs = json.loads(segs_path.read_text(encoding="utf-8"))
        except Exception:
            segs = []
    return Re, Im, Z, ids, segs


def _load_asf_assets(cache_dir: Path, kind: str):
    from . import vocab as V
    vocab_path  = cache_dir / f"vocab_{kind}.json"
    tokset_path = cache_dir / f"{kind}_token_sets.json"
    vocab = V.load_vocab(vocab_path)
    toks  = V.load_token_sets(tokset_path)
    return vocab, toks


def search_movie(query: str, topk: int = 5,
                 siglip_encoder=None, bge_encoder=None,
                 cache_dir: Path | None = None) -> list[SearchHit]:
    from .paths import MOVIE_CACHE_DIR
    cache_dir = cache_dir or MOVIE_CACHE_DIR

    Re, Im, Z, ids, segs = _load_domain(cache_dir, "movie")
    if Re.shape[0] == 0:
        return []

    q_sig = None
    if siglip_encoder is not None:
        v = siglip_encoder.embed_texts([query])
        if v.size:
            q_sig = v[0]

    q_bge = bge_encoder.embed([query])[0] if bge_encoder is not None else None

    A = _cos(q_sig, Re) if q_sig is not None else np.zeros(Re.shape[0], dtype=np.float32)
    B = _cos(q_bge, Im) if q_bge is not None else np.zeros(Im.shape[0], dtype=np.float32)
    per_seg_dense = np.sqrt(A**2 + (0.4 * B)**2).astype(np.float32)

    vocab, toks = _load_asf_assets(cache_dir, "movie")
    return _aggregate(per_seg_dense, ids, segs, topk,
                      domain="movie", query=query, vocab=vocab, token_sets=toks)


def search_music(query: str, topk: int = 5,
                 siglip_encoder=None, bge_encoder=None,
                 cache_dir: Path | None = None) -> list[SearchHit]:
    from .paths import MUSIC_CACHE_DIR
    cache_dir = cache_dir or MUSIC_CACHE_DIR

    Re, Im, Z, ids, segs = _load_domain(cache_dir, "music")
    if Re.shape[0] == 0:
        return []

    # Music Re 는 SigLIP2-text 1152d (2026-04 전환) — q_sig 로 내적.
    # Im 은 BGE-M3 1024d — q_bge 로 내적. Movie 와 동일한 크로스모달 공식.
    q_sig = None
    if siglip_encoder is not None:
        v = siglip_encoder.embed_texts([query])
        if v.size:
            q_sig = v[0]
    q_bge = bge_encoder.embed([query])[0] if bge_encoder is not None else None

    A = _cos(q_sig, Re) if q_sig is not None else np.zeros(Re.shape[0], dtype=np.float32)
    B = _cos(q_bge, Im) if q_bge is not None else np.zeros(Im.shape[0], dtype=np.float32)
    per_seg_dense = np.sqrt(A**2 + (0.4 * B)**2).astype(np.float32)

    vocab, toks = _load_asf_assets(cache_dir, "music")
    return _aggregate(per_seg_dense, ids, segs, topk,
                      domain="music", query=query, vocab=vocab, token_sets=toks)


def _aggregate(per_seg_dense: np.ndarray, ids: list[str], segs: list[dict],
               topk: int, domain: str, query: str,
               vocab: dict, token_sets: list[dict]) -> list[SearchHit]:
    """세그먼트 dense score → 파일 top-3 평균 → z-score.  ASF 점수와 가중 합산.

    final_score = α · z_dense + β · lexical + γ · asf_per_file
    """
    from . import calibration, asf as asf_mod
    if len(per_seg_dense) == 0 or len(ids) != len(per_seg_dense):
        return []

    # 세그먼트 단위 ASF (없으면 0 벡터)
    if vocab and token_sets and len(token_sets) == len(ids):
        asf_seg = asf_mod.asf_scores(query, token_sets, vocab)
    else:
        asf_seg = np.zeros_like(per_seg_dense)

    # 파일별 세그먼트 인덱스 수집
    file_idx: dict[str, list[int]] = {}
    for i, rel in enumerate(ids):
        file_idx.setdefault(rel, []).append(i)

    alpha, beta, gamma = WEIGHTS.get(domain, (1.0, 0.0, 0.0))
    cal = calibration.load()

    hits: list[SearchHit] = []
    for rel, idxs in file_idx.items():
        d_scores = [(i, float(per_seg_dense[i])) for i in idxs]
        d_top = sorted(d_scores, key=lambda x: -x[1])[:3]
        dense_agg = float(np.mean([s for (_i, s) in d_top])) if d_top else 0.0

        # ASF 는 파일 내 max (정규화 후 [0,1])
        a_vals = [float(asf_seg[i]) for i in idxs]
        asf_agg = float(max(a_vals)) if a_vals else 0.0

        z_dense, _ = calibration.normalize(dense_agg, domain, cal)

        final = alpha * z_dense + gamma * asf_agg
        # confidence: sigmoid on final (ASF 포함 스케일 반영)
        import math as _m
        conf = 1.0 / (1.0 + _m.exp(-final / 2.0))

        seg_list: list[dict] = []
        best_i = d_top[0][0] if d_top else idxs[0]
        for (i, s) in d_top:
            if i < len(segs):
                meta = dict(segs[i])
                meta["score_raw"] = round(s, 4)
                meta["asf"] = round(float(asf_seg[i]), 4)
                seg_list.append(meta)
        fname = Path(rel).name
        if segs and best_i < len(segs):
            fname = segs[best_i].get("file_name", fname)

        hits.append(SearchHit(
            file=rel, file_name=fname,
            score=round(final, 4),
            confidence=round(conf, 4),
            segments=seg_list,
        ))
    hits.sort(key=lambda h: -h.score)
    return hits[:topk]
