"""vocab + token_sets 재빌드 (sparse 행렬 제외 — GPU 불필요)."""
import sys, time, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from pathlib import Path
from config import PATHS
from services.trichef.lexical_rebuild import _av_stt_texts
from services.trichef import auto_vocab, asf_filter

print(f"[START] vocab+token_sets rebuild — {time.strftime('%H:%M:%S')}")
t0 = time.time()

cache = Path(PATHS["TRICHEF_MOVIE_CACHE"])
segs_path = cache / "segments.json"
segments = json.loads(segs_path.read_text(encoding="utf-8"))
texts = _av_stt_texts(segments)

vocab = auto_vocab.build_vocab(texts, min_df=2, max_df_ratio=0.5, top_k=25000)
auto_vocab.save_vocab(cache / "vocab_movie.json", vocab)
print(f"vocab: {len(vocab)} ({time.time()-t0:.1f}s)")

# cosmos/voyager 확인
for kw in ['cosmos','voyager','golden','ngc','space','probe','spacecraft']:
    matches = [k for k in vocab if kw in k.lower()]
    if matches:
        print(f"  [{kw}]: {matches[:4]}")

sets = asf_filter.build_doc_token_sets(texts, vocab)
asf_filter.save_token_sets(cache / "movie_token_sets.json", sets)

nonempty = sum(1 for s in sets if s)
print(f"token_sets: {nonempty}/{len(sets)} non-empty ({nonempty/len(sets)*100:.1f}%)")

# 보이저 포함 확인
voy = sum(1 for s in sets if any('voyager' in k.lower() or '보이저' in k for k in s))
cos = sum(1 for s in sets if any('cosmos' in k.lower() or '코스모스' in k for k in s))
print(f"  voyager/보이저 포함: {voy}, cosmos/코스모스 포함: {cos}")
print(f"[DONE] {time.time()-t0:.1f}s")
