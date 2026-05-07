"""다양한 쿼리로 4 도메인 검색 정확도 종합 점검.

각 쿼리 → engine 직접 호출 → top-3 결과 + 도메인 + conf 출력.
사람이 검토하기 쉬운 형식으로.
"""
import sys, os, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "App/backend")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
os.environ.setdefault("TRICHEF_USE_RERANKER", "0")

import logging
logging.basicConfig(level=logging.WARNING)

from services.trichef.unified_engine import TriChefEngine

print("[check_search_quality] 엔진 로드 중...", flush=True)
e = TriChefEngine()
print("로드 완료\n", flush=True)

# 쿼리 카테고리 별 다양한 검색
TEST_CASES = [
    # === Rec (음성) — 인명 + STT 본문 ===
    ("박태웅 의장", "music"),
    ("AI 시대 박태웅", "music"),
    ("바이브 코딩", "music"),
    ("AI 에이전트", "music"),
    ("트럼프 대통령", "music"),
    ("미국 출장", "music"),
    ("국가인공지능전략위원회", "music"),

    # === Movie (영상) — 인명 + STT + 시각 ===
    ("박덕흠 공관위", "movie"),
    ("장동혁 대구", "movie"),
    ("홍준표 김부겸", "movie"),
    ("야구 라이징이글스", "movie"),
    ("물리학자 양자역학", "movie"),
    ("롯데 야구", "movie"),
    ("뉴스데스크 MBC", "movie"),

    # === Img (이미지) — 자연어 + 객체 + 캡션 ===
    ("바다", "image"),
    ("고양이", "image"),
    ("커피 카페", "image"),
    ("스시 음식", "image"),
    ("자동차", "image"),
    ("산 풍경", "image"),
    ("korean food", "image"),
    ("beach sunset", "image"),

    # === Doc (문서) — 보고서명 + 본문 ===
    ("AI 브리프", "doc_page"),
    ("SW산업 실태조사", "doc_page"),
    ("VR AR 산업", "doc_page"),
    ("월간 SW중심사회", "doc_page"),
    ("인공지능 법", "doc_page"),
    ("클라우드 도입률", "doc_page"),  # 본문 키워드
    ("디지털 전환", "doc_page"),
    ("데이터센터", "doc_page"),
]

print(f"{'='*100}")
print(f"검색 정확도 종합 점검 (총 {len(TEST_CASES)} 쿼리)")
print(f"{'='*100}\n")

for q, dom in TEST_CASES:
    label = {"music": "🎵 Rec", "movie": "🎬 Movie",
             "image": "🖼  Img", "doc_page": "📄 Doc"}[dom]
    print(f"{label} | 쿼리: '{q}'")
    print("-" * 100)
    t0 = time.time()
    try:
        if dom in ("movie", "music"):
            res = e.search_av(q, dom, topk=3)
            for i, r in enumerate(res, 1):
                fn = r.file_name[:60]
                print(f"  #{i}  conf={r.confidence:.3f} | {fn}")
        else:
            res = e.search(q, dom, topk=3, use_lexical=True, use_asf=True, pool=200)
            for i, r in enumerate(res, 1):
                # Doc id format: page_images/<stem>/p####.jpg
                rid = r.id
                if rid.startswith("page_images/"):
                    fname = rid.split("/", 2)[1] + ".pdf"
                else:
                    fname = rid.replace("\\", "/").rsplit("/", 1)[-1]
                print(f"  #{i}  conf={r.confidence:.3f} | {fname[:60]}")
    except Exception as ex:
        print(f"  ERROR: {ex}")
    print(f"  ({time.time()-t0:.2f}s)\n")
