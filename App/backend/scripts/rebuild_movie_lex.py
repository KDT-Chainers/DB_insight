"""movie lexical 재빌드 — GPU RTX 4070 활용."""
import sys, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

print(f"[START] movie lexical rebuild — {time.strftime('%H:%M:%S')}")

# GPU 확인
try:
    import torch
    print(f"CUDA: {torch.cuda.is_available()}, device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
except Exception as e:
    print(f"torch 확인 실패: {e}")

from services.trichef.lexical_rebuild import rebuild_movie_lexical

t0 = time.time()
result = rebuild_movie_lexical()
elapsed = time.time() - t0

print(f"\n[DONE] {elapsed:.1f}s")
print(f"결과: {result}")
