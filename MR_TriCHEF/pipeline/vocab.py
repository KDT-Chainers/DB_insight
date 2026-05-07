"""도메인 자동 어휘 (auto_vocab) — STT 말뭉치에서 IDF 기반 핵심 어휘 추출.

출력: {token: {"df": N, "idf": float}} JSON — ASF 필터가 쿼리↔세그먼트 오버랩 점수
      계산 시 가중치 소스로 활용.

App/backend/services/trichef/auto_vocab.py 포팅. 토크나이저/스톱워드는 동일.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path


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


def tokenize(text: str) -> list[str]:
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
                max_df_ratio: float = 0.5, top_k: int | None = None) -> dict:
    """docs: 세그먼트/윈도우별 텍스트 리스트.  반환: {token: {df, idf}}."""
    N = max(len(docs), 1)
    df: Counter = Counter()
    for text in docs:
        uniq = set(tokenize(text))
        for t in uniq:
            df[t] += 1

    max_df = max(int(N * max_df_ratio), 1)
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
    path.write_text(json.dumps(vocab, ensure_ascii=False, indent=2), encoding="utf-8")


def load_vocab(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_token_sets(docs: list[str], vocab: dict) -> list[dict[str, float]]:
    """세그먼트별 {token: idf}. 한글은 조사·접미사 절단(1~3자) 재매칭 포함."""
    def _is_kr(s: str) -> bool:
        return any("\uac00" <= c <= "\ud7a3" for c in s)

    out: list[dict[str, float]] = []
    for text in docs:
        toks = set(tokenize(text))
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sets, ensure_ascii=False), encoding="utf-8")


def load_token_sets(path: Path) -> list[dict[str, float]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))
