"""GPU 스파스 매트릭스 재빌딩 — movie + music (metadata 포함 버전)
   _av_stt_texts()에 metadata_map을 전달해 title/tags/synopsis가
   BGE-M3 sparse 인코딩에도 포함됨 → 'sagan', 'cosmos', 'astronomy' 등
   sparse 채널에서도 매칭 가능.
"""
import sys, time, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from pathlib import Path
from scipy import sparse as sp
from config import PATHS
from services.trichef.lexical_rebuild import (
    _av_stt_texts, _encode_sparse, _load_metadata_map,
)

try:
    import torch
    cuda_ok = torch.cuda.is_available()
    dev_name = torch.cuda.get_device_name(0) if cuda_ok else 'CPU'
    print(f"[GPU] CUDA={cuda_ok}  device={dev_name}")
except Exception as e:
    print(f"[GPU] torch 확인 실패: {e}")

total_t0 = time.time()

# ── MOVIE (with metadata) ─────────────────────────────────────────────
print(f"\n[MOVIE] sparse 재빌드 시작 {time.strftime('%H:%M:%S')}")
t0 = time.time()
cache = Path(PATHS["TRICHEF_MOVIE_CACHE"])
segments = json.loads((cache / "segments.json").read_text(encoding="utf-8"))
meta_map = _load_metadata_map(cache / "movie_metadata.json")
print(f"  metadata entries={len(meta_map)//2}")
texts = _av_stt_texts(segments, metadata_map=meta_map)
print(f"  texts={len(texts)}")
print(f"  sample[NGC E01]: {texts[next(i for i,s in enumerate(segments) if 'NGC 코스모스 E01' in str(s.get('file_name','')))][:150]}")
mat = _encode_sparse(texts, max_length=512)
sp.save_npz(cache / "cache_movie_sparse.npz", mat)
print(f"  [MOVIE] shape={mat.shape} nnz={mat.nnz} ({time.time()-t0:.1f}s)")

# ── MUSIC ────────────────────────────────────────────────────────────
print(f"\n[MUSIC] sparse 재빌드 시작 {time.strftime('%H:%M:%S')}")
t0 = time.time()
cache = Path(PATHS["TRICHEF_MUSIC_CACHE"])
segments = json.loads((cache / "segments.json").read_text(encoding="utf-8"))
texts = _av_stt_texts(segments)   # music no metadata yet
print(f"  texts={len(texts)}")
mat = _encode_sparse(texts, max_length=512)
sp.save_npz(cache / "cache_music_sparse.npz", mat)
print(f"  [MUSIC] shape={mat.shape} nnz={mat.nnz} ({time.time()-t0:.1f}s)")

print(f"\n[ALL DONE] total={time.time()-total_t0:.1f}s  {time.strftime('%H:%M:%S')}")
