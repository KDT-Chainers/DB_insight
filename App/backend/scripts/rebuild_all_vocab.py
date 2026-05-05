"""전 도메인 vocab + token_sets 재빌드 (sparse 행렬 제외 — GPU 불필요).
   Movie, Rec 도메인 대상.
   movie_metadata.json 이 cache 에 있으면 메타데이터를 텍스트에 포함해
   dense/sparse/ASF 모두 메타 기반 검색 지원.
"""
import sys, time, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from pathlib import Path
from config import PATHS
from services.trichef.lexical_rebuild import (
    _av_stt_texts, _inject_domain_keywords,
    _load_metadata_map,
)
from services.trichef import auto_vocab, asf_filter

def rebuild_vocab_only(cache_path, segs_file, vocab_file, sets_file, domain,
                       top_k, min_df=2, max_df_ratio=0.5,
                       metadata_file: str | None = None):
    cache = Path(cache_path)
    segs_path = cache / segs_file
    if not segs_path.exists():
        print(f"  [{domain}] SKIP: {segs_file} 없음")
        return
    t0 = time.time()
    segments = json.loads(segs_path.read_text(encoding='utf-8'))

    # 메타데이터 로드 (있으면 텍스트에 삽입)
    meta_map = {}
    if metadata_file:
        meta_path = cache / metadata_file
        meta_map = _load_metadata_map(meta_path)
        print(f"  [{domain}] metadata entries: {len(meta_map)//2}")

    texts = _av_stt_texts(segments, metadata_map=meta_map if meta_map else None)

    vocab = auto_vocab.build_vocab(texts, min_df=min_df,
                                   max_df_ratio=max_df_ratio, top_k=top_k)
    vocab = _inject_domain_keywords(vocab, domain)
    auto_vocab.save_vocab(cache / vocab_file, vocab)

    sets = asf_filter.build_doc_token_sets(texts, vocab)
    asf_filter.save_token_sets(cache / sets_file, sets)

    nonempty = sum(1 for s in sets if s)
    forced = [k for k in vocab if vocab[k]['df'] == 0]
    print(f"  [{domain}] vocab={len(vocab)} (forced={len(forced)}) "
          f"token_sets={nonempty}/{len(sets)} ({nonempty/len(sets)*100:.1f}%) "
          f"({time.time()-t0:.1f}s)")
    # 핵심어 확인
    for kw in ['cosmos','voyager','golden','drum','bass','guitar','jazz','rock',
               'silk road','silkroad','carl','sagan']:
        if kw in vocab:
            print(f"    [{kw}] ✓ df={vocab[kw]['df']} idf={vocab[kw]['idf']:.2f}")

print(f"[START] {time.strftime('%H:%M:%S')}")

rebuild_vocab_only(
    PATHS["TRICHEF_MOVIE_CACHE"], "segments.json",
    "vocab_movie.json", "movie_token_sets.json",
    domain="movie", top_k=25000,
    metadata_file="movie_metadata.json"
)
rebuild_vocab_only(
    PATHS["TRICHEF_MUSIC_CACHE"], "segments.json",
    "vocab_music.json", "music_token_sets.json",
    domain="music", top_k=15000
)

print(f"[DONE] {time.strftime('%H:%M:%S')}")
