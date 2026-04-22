"""services/trichef/auto_vocab.py — 도메인 자동 어휘 추출 (v3 P3).

이미지/문서 캡션 + PDF 원문에서 빈도·IDF 기반 핵심 어휘 추출.
출력: {token: {"df": N, "idf": float}} JSON — ASF 필터에서 쿼리↔문서 오버랩
시 가중치 소스로 활용.
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)


_TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9\-]{2,}")

_KO_STOP = {
    "있는", "있다", "없는", "없다", "하는", "하여", "되는", "되어", "위한",
    "이것", "그것", "저것", "우리", "그리고", "그러나", "또한", "때문", "경우",
    "대한", "위하여", "이번", "부터", "까지", "에서", "으로", "에게", "에서도",
    "및", "등", "등등", "이하", "이상", "관련", "대상", "기관", "사업", "관한",
}
_EN_STOP = {
    "the","a","an","of","in","on","at","with","and","or","is","are","was","were",
    "for","to","by","as","from","be","has","have","had","showing","photo","image",
    "picture","this","that","it","its","which","what","who","whom","whose","their",
}


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    out = []
    for m in _TOKEN_RE.findall(text):
        w = m.strip().lower() if m[0].isascii() else m.strip()
        if not w:
            continue
        if w in _EN_STOP or w in _KO_STOP:
            continue
        out.append(w)
    return out


def build_vocab(docs: list[str], min_df: int = 2,
                max_df_ratio: float = 0.4, top_k: int | None = None) -> dict:
    """
    docs: 문서별 텍스트 리스트 (한 줄 문서 하나)
    반환: {token: {"df": int, "idf": float}}
    """
    N = len(docs)
    df: Counter = Counter()
    for text in docs:
        uniq = set(_tokenize(text))
        for t in uniq:
            df[t] += 1

    max_df = int(N * max_df_ratio)
    vocab: dict = {}
    for t, c in df.items():
        if c < min_df or c > max_df:
            continue
        idf = math.log((N + 1) / (c + 1)) + 1.0
        vocab[t] = {"df": c, "idf": round(idf, 4)}

    if top_k is not None:
        sorted_items = sorted(vocab.items(), key=lambda kv: -kv[1]["idf"])[:top_k]
        vocab = dict(sorted_items)

    return vocab


def save_vocab(path: Path, vocab: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(vocab, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def load_vocab(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
