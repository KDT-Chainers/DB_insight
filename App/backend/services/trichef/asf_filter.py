"""services/trichef/asf_filter.py — Attention-Similarity-Filter (v3 P4).

쿼리↔문서 간 도메인 어휘 오버랩 기반 보정 점수.
소스: auto_vocab.json ({token: {df, idf}}) + 문서별 텍스트(캡션+원문).

사용: final = α·dense + β·lexical_norm + γ·asf_score
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np

from services.trichef.auto_vocab import _tokenize, load_vocab

logger = logging.getLogger(__name__)


def build_doc_token_sets(docs: list[str], vocab: dict) -> list[dict[str, float]]:
    """문서별 {token: idf} — vocab 에 속하는 토큰만 유지."""
    out: list[dict[str, float]] = []
    for text in docs:
        toks = set(_tokenize(text))
        entry = {t: float(vocab[t]["idf"]) for t in toks if t in vocab}
        out.append(entry)
    return out


def save_token_sets(path: Path, sets: list[dict[str, float]]) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sets, ensure_ascii=False), encoding="utf-8")


def load_token_sets(path: Path) -> list[dict[str, float]]:
    import json
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def asf_scores(query: str, doc_token_sets: list[dict[str, float]],
               vocab: dict) -> np.ndarray:
    """쿼리 토큰 ∩ 문서 토큰의 IDF 합을 문서별로 계산, 정규화.

    score_i = Σ_{t ∈ Q ∩ D_i} idf(t)   → min-max 정규화 → [0, 1]
    """
    n = len(doc_token_sets)
    if n == 0:
        return np.zeros(0, dtype=np.float32)

    raw = _tokenize(query)
    if not raw:
        return np.zeros(n, dtype=np.float32)
    # 한글은 조사 결합으로 compound 형태로만 vocab 에 존재하는 경우가 많음.
    # 길이 2+ 한글 토큰은 vocab substring 매칭으로 확장.
    q_set: set[str] = set()
    for t in raw:
        if t in vocab:
            q_set.add(t)
        if any("\uac00" <= c <= "\ud7a3" for c in t) and len(t) >= 2:
            for vt in vocab:
                if t in vt:
                    q_set.add(vt)
    if not q_set:
        return np.zeros(n, dtype=np.float32)
    q_norm = math.sqrt(sum(vocab[t]["idf"] ** 2 for t in q_set)) or 1.0

    scores = np.zeros(n, dtype=np.float32)
    for i, d in enumerate(doc_token_sets):
        if not d:
            continue
        inter = q_set & d.keys()
        if not inter:
            continue
        num = sum(d[t] for t in inter)
        scores[i] = num / q_norm

    mx = float(scores.max())
    if mx > 0:
        scores = scores / mx
    return scores
