"""Doc 도메인 검색 직접 테스트 (백엔드 없이)."""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "App/backend")
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
import logging
logging.basicConfig(level=logging.WARNING)

from services.trichef.unified_engine import TriChefEngine

print("Engine 로드 중...")
e = TriChefEngine()
print(f"cache 도메인: {list(e._cache.keys())}")
d = e._cache.get("doc_page")
if d is None:
    print("ERROR: doc_page cache 미로드!")
    sys.exit(1)
print(f"doc_page: Re={d['Re'].shape}, ids={len(d['ids'])}, sparse={'O' if d.get('sparse') is not None else 'X'}, asf_sets={'O' if d.get('asf_sets') else 'X'}")

# Doc 검색
queries = ["AI브리프", "SPRI", "SW중심사회", "산업 연간 보고서", "통계", "이전간행물", "AI 브리프 12월호"]
for q in queries:
    print(f"\n=== Doc 검색: {q!r} ===")
    res = e.search(q, "doc_page", topk=10)
    print(f"  결과 수: {len(res)}")
    for i, r in enumerate(res[:5]):
        print(f"  #{i+1} conf={r.confidence:.3f} score={r.score:.3f} id={r.id[:80]}")
