"""services/trichef/asf_filter.py — Adaptive Sieve Filter (v3 P4).

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


def _is_kr(s: str) -> bool:
    return any("\uac00" <= c <= "\ud7a3" for c in s)


def build_doc_token_sets(docs: list[str], vocab: dict) -> list[dict[str, float]]:
    """문서별 {token: idf} — vocab 매칭 (한글 조사/접미 제거 후 재매칭 포함).

    한국어는 "지역사회의", "금융이"처럼 조사가 붙어 추출되는 경우가 많아,
    exact 매치 외에 1~3자 말미 절단(접사/조사 근사) 매칭을 시도한다.
    """
    out: list[dict[str, float]] = []
    for text in docs:
        toks = set(_tokenize(text))
        entry: dict[str, float] = {}
        for t in toks:
            if t in vocab:
                entry[t] = float(vocab[t]["idf"])
            if _is_kr(t) and len(t) >= 3:
                for strip in (1, 2, 3):
                    if len(t) - strip >= 2:
                        sub = t[:-strip]
                        if sub in vocab and sub not in entry:
                            entry[sub] = float(vocab[sub]["idf"])
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


# 한글 bigram → vocab 토큰 역색인 캐시 (vocab dict id 기준 메모이제이션).
_bigram_index_cache: dict[int, dict[str, list[str]]] = {}


def _get_kr_bigram_index(vocab: dict) -> dict[str, list[str]]:
    key = id(vocab)
    idx = _bigram_index_cache.get(key)
    if idx is not None:
        return idx
    idx = {}
    for vt in vocab:
        if not any("\uac00" <= c <= "\ud7a3" for c in vt):
            continue
        seen = set()
        for i in range(len(vt) - 1):
            bg = vt[i:i+2]
            if bg in seen:
                continue
            seen.add(bg)
            idx.setdefault(bg, []).append(vt)
    _bigram_index_cache[key] = idx
    return idx


def _bilingual_expand(query: str) -> str:
    """query_expand.expand_bilingual() 로 한↔영 확장. 실패 시 원본 반환."""
    try:
        from services.query_expand import expand_bilingual
        return expand_bilingual(query)
    except Exception:
        return query


def asf_scores(query: str, doc_token_sets: list[dict[str, float]],
               vocab: dict) -> np.ndarray:
    """쿼리 토큰 ∩ 문서 토큰의 IDF 합을 문서별로 계산, 정규화.

    score_i = Σ_{t ∈ Q ∩ D_i} idf(t)   → min-max 정규화 → [0, 1]

    쿼리는 bilingual 확장 후 토크나이징 → 한↔영 크로스랭귀지 매칭 지원.
    """
    n = len(doc_token_sets)
    if n == 0:
        return np.zeros(0, dtype=np.float32)

    # 한↔영 확장으로 크로스랭귀지 토큰 추가
    expanded_query = _bilingual_expand(query)
    raw = _tokenize(expanded_query)
    if not raw:
        return np.zeros(n, dtype=np.float32)
    # 한글은 조사 결합으로 compound 형태로만 vocab 에 존재하는 경우가 많음.
    # 길이 2+ 한글 토큰은 vocab substring 매칭으로 확장.
    q_set: set[str] = set()
    kr_idx = None
    for t in raw:
        if t in vocab:
            q_set.add(t)
        if any("\uac00" <= c <= "\ud7a3" for c in t) and len(t) >= 2:
            if kr_idx is None:
                kr_idx = _get_kr_bigram_index(vocab)
            # 후보: t 의 모든 bigram 으로 색인된 vocab 토큰들의 합집합.
            candidates: set[str] = set()
            for i in range(len(t) - 1):
                bucket = kr_idx.get(t[i:i+2])
                if bucket:
                    candidates.update(bucket)
            for vt in candidates:
                if t in vt:
                    q_set.add(vt)
    if not q_set:
        return np.zeros(n, dtype=np.float32)
    # vocab 형식 양립: {token: {"idf": float}} (legacy) vs {token: float} (rebuild_asf_vocab.py)
    def _idf(t):
        v = vocab[t]
        return float(v) if isinstance(v, (int, float)) else float(v.get("idf", 1.0))
    q_norm = math.sqrt(sum(_idf(t) ** 2 for t in q_set)) or 1.0

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
