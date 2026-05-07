"""routes/search.py 의 통합 검색 직접 호출 (백엔드 없이)."""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "App/backend")
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ.setdefault("TRICHEF_USE_RERANKER", "0")  # rerank off for speed
import logging
logging.basicConfig(level=logging.WARNING)

from routes.search import _search_trichef, _search_trichef_av

queries = ["AI브리프", "박태웅 의장", "SW중심사회", "주연 텍스트 샘플", "korean cafe"]
for q in queries:
    print(f"\n=== 통합 검색 시뮬레이션: {q!r} (top_k=20) ===")
    img_only = _search_trichef(q, ["image"], 20)
    doc_only = _search_trichef(q, ["doc_page"], 20)
    video    = _search_trichef_av(q, ["movie"], 20)
    audio    = _search_trichef_av(q, ["music"], 20)
    print(f"  도메인별 결과: img={len(img_only)}, doc={len(doc_only)}, video={len(video)}, audio={len(audio)}")
    for label, lst in (("doc", doc_only), ("img", img_only), ("video", video), ("audio", audio)):
        lst.sort(key=lambda r: r.get("confidence", 0), reverse=True)
        if lst:
            top3 = lst[:3]
            for r in top3:
                fn = (r.get('file_name') or '')[:50]
                print(f"    [{label}] conf={r.get('confidence'):.3f} {fn}")
