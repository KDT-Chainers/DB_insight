"""인덱싱 완료 후 ASF 자산(vocab + token_sets) 일괄 빌드.

- segments.json 의 stt_text 를 말뭉치로 vocab_{domain}.json 생성
- 동일 순서로 {domain}_token_sets.json 생성
"""
from __future__ import annotations

import json
from pathlib import Path

from . import vocab as V
from .paths import MOVIE_CACHE_DIR, MUSIC_CACHE_DIR


def _load_segments(cache_dir: Path) -> list[dict]:
    p = cache_dir / "segments.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def build_for(cache_dir: Path, kind: str) -> dict:
    segs = _load_segments(cache_dir)
    if not segs:
        return {"status": "no_segments", "n": 0}

    texts = [(s.get("stt_text") or "") for s in segs]
    vocab = V.build_vocab(texts, min_df=2, max_df_ratio=0.5, top_k=20000)
    V.save_vocab(cache_dir / f"vocab_{kind}.json", vocab)

    toks = V.build_token_sets(texts, vocab)
    V.save_token_sets(cache_dir / f"{kind}_token_sets.json", toks)
    return {"status": "ok", "n": len(segs), "vocab_size": len(vocab)}


def build_all() -> dict:
    return {
        "movie": build_for(MOVIE_CACHE_DIR, "movie"),
        "music": build_for(MUSIC_CACHE_DIR, "music"),
    }


if __name__ == "__main__":
    import json as _j
    print(_j.dumps(build_all(), ensure_ascii=False, indent=2))
