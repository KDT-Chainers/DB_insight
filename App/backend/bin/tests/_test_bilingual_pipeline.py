"""
Bilingual search pipeline verification.
Tests Korean↔English cross-lingual search across all 5 domains.
"""
from __future__ import annotations
import sys, io, time
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TOP_K = 5

# ── Test pairs: (korean_query, english_query, topic, domains) ─────────────
PAIRS = [
    ("농구 경기",          "basketball game",              "basketball",   ["movie","music"]),
    ("야구 홈런",          "baseball home run",            "baseball",     ["movie"]),
    ("축구 국가대표",       "soccer national team",         "soccer",       ["movie"]),
    ("주식 투자 경제",      "stock market investment",      "economy",      ["movie","music"]),
    ("인공지능 AI 기술",    "artificial intelligence",      "AI",           ["movie","music"]),
    ("선거 정치",          "election politics",            "election",     ["movie"]),
    ("연예대상 시상식",     "entertainment award ceremony", "award",        ["movie","music"]),
    ("과학 물리 양자역학",  "science physics quantum",      "science",      ["movie","music"]),
    ("상담 면담 선생님",    "teacher consultation",         "counseling",   ["music"]),
    ("창업 스타트업",       "startup entrepreneurship",     "startup",      ["music"]),
    # BGM pairs
    ("잔잔한 피아노",       "calm piano background music",  "calm_bgm",     ["bgm"]),
    ("신나는 빠른 음악",    "upbeat fast energetic music",  "fast_bgm",     ["bgm"]),
    ("어두운 긴장감",       "dark tense dramatic music",    "dark_bgm",     ["bgm"]),
    # Image pairs — BLIP 캡션 기반 (영어 캡션, SigLIP2+BGE-M3 검색)
    ("고양이",             "cat feline",                   "cat_img",      ["image"]),
    ("강아지 개",           "dog puppy",                    "dog_img",      ["image"]),
    ("해변 바다",           "beach ocean sea",              "beach_img",    ["image"]),
    ("노을 일몰",           "sunset",                       "sunset_img",   ["image"]),
    ("음식 요리",           "food meal dish",               "food_img",     ["image"]),
    ("산 자연 풍경",        "mountain landscape nature",    "mountain_img", ["image"]),
    ("꽃 식물",             "flower plant",                 "flower_img",   ["image"]),
    ("건물 도시",           "building city architecture",   "building_img", ["image"]),
    # Doc pairs — 실제 문서 제목 기반 (연도 특정으로 ambiguity 최소화)
    ("2024 인공지능산업 실태조사",         "2024 AI industry survey report",          "AI_doc",     ["doc_page"]),
    ("2023년 소프트웨어산업 연간보고서",   "2023 software industry annual report",    "SW_doc",     ["doc_page"]),
    ("삼성전자 지속가능성",            "Samsung Electronics sustainability",    "samsung_doc",["doc_page"]),
    ("식량 가격 지수 농업",            "food price index FAO agriculture",      "food_doc",   ["doc_page"]),
]

def overlap(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)

def short(s: str, n: int = 55) -> str:
    name = s.split("/")[-1].split("\\")[-1]
    return name[:n] + ("…" if len(name) > n else "")


# ── Load engines ──────────────────────────────────────────────────────────
print("Loading TRI-CHEF engine…", flush=True)
t0 = time.time()
from services.trichef.unified_engine import TriChefEngine
engine = TriChefEngine()
print(f"  ready in {time.time()-t0:.1f}s")

print("Loading BGM engine…", flush=True)
from services.bgm.search_engine import get_engine as get_bgm
bgm = get_bgm()
bgm._ensure_loaded()
print(f"  BGM text_idx={'OK' if bgm._text_index is not None else 'MISS'}")


# ── Run tests ─────────────────────────────────────────────────────────────
print("\n" + "="*80)
print("BILINGUAL CROSS-LINGUAL VERIFICATION")
print("="*80)

total_pairs = 0
passed_pairs = 0

for ko_q, en_q, topic, domains in PAIRS:
    print(f"\n[{topic}]  KO={ko_q!r}  EN={en_q!r}")

    for domain in domains:
        if domain == "bgm":
            # BGM
            r_ko = bgm.search(ko_q, top_k=TOP_K)["results"]
            r_en = bgm.search(en_q, top_k=TOP_K)["results"]
            ko_fns = [r["filename"] for r in r_ko]
            en_fns = [r["filename"] for r in r_en]
            print(f"  [bgm] KO top-3:")
            for r in r_ko[:3]:
                print(f"    a={r['audio_score']:.3f} t={r['text_score']:.3f} "
                      f"fused={r['score']:.3f} conf={r['confidence']:.2f}  "
                      f"{short(r['filename'])} | {r['description'][:50]}")
            print(f"  [bgm] EN top-3:")
            for r in r_en[:3]:
                print(f"    a={r['audio_score']:.3f} t={r['text_score']:.3f} "
                      f"fused={r['score']:.3f} conf={r['confidence']:.2f}  "
                      f"{short(r['filename'])} | {r['description'][:50]}")
        elif domain in ("image", "doc_page"):
            # TRI-CHEF Image / Doc — engine.search() 사용 (AV 와 다른 API)
            # [중요] 라우트(/api/search)와 동일하게 expand_bilingual 적용 후 검색.
            # 이렇게 해야 KO 쿼리에 EN 토큰이 추가되어 영문 캡션/문서와 매칭 가능.
            from services.query_expand import expand_bilingual as _ebil
            ko_exp = _ebil(ko_q)
            en_exp = _ebil(en_q)
            try:
                r_ko = engine.search(ko_exp, domain=domain, topk=TOP_K,
                                     use_lexical=True, use_asf=True)
                r_en = engine.search(en_exp, domain=domain, topk=TOP_K,
                                     use_lexical=True, use_asf=True)
            except Exception as e:
                print(f"  [{domain}] ERROR: {e}")
                continue
            # doc_page: id = "page_images/문서명/pNNNN.jpg" → 문서명 단위로 overlap
            def _doc_key(rid: str) -> str:
                parts = rid.replace("\\", "/").split("/")
                return parts[1] if len(parts) >= 3 else rid
            if domain == "doc_page":
                ko_fns = [_doc_key(r.id) for r in r_ko]
                en_fns = [_doc_key(r.id) for r in r_en]
            else:
                ko_fns = [r.id for r in r_ko]
                en_fns = [r.id for r in r_en]
            print(f"  [{domain}] KO top-3:")
            for r in r_ko[:3]:
                key = _doc_key(r.id) if domain == "doc_page" else r.id
                print(f"    score={r.score:.3f} conf={r.confidence:.2f}  {short(key)}")
            print(f"  [{domain}] EN top-3:")
            for r in r_en[:3]:
                key = _doc_key(r.id) if domain == "doc_page" else r.id
                print(f"    score={r.score:.3f} conf={r.confidence:.2f}  {short(key)}")
        else:
            # TRI-CHEF AV (movie/music)
            try:
                r_ko = engine.search_av(ko_q, domain=domain, topk=TOP_K)
                r_en = engine.search_av(en_q, domain=domain, topk=TOP_K)
            except Exception as e:
                print(f"  [{domain}] ERROR: {e}")
                continue
            ko_fns = [r.file_name for r in r_ko]
            en_fns = [r.file_name for r in r_en]
            print(f"  [{domain}] KO top-3:")
            for r in r_ko[:3]:
                print(f"    score={r.score:.3f} conf={r.confidence:.2f}  {short(r.file_name)}")
            print(f"  [{domain}] EN top-3:")
            for r in r_en[:3]:
                print(f"    score={r.score:.3f} conf={r.confidence:.2f}  {short(r.file_name)}")

        ov = overlap(ko_fns[:3], en_fns[:3])
        tag = "✓ PASS" if ov >= 0.33 else "✗ FAIL"
        print(f"  [{domain}] overlap@3 = {ov:.2f}  {tag}")
        total_pairs += 1
        if ov >= 0.33:
            passed_pairs += 1

print("\n" + "="*80)
pct = passed_pairs/total_pairs*100 if total_pairs else 0
print(f"SUMMARY: {passed_pairs}/{total_pairs} pairs passed  ({pct:.0f}%)  threshold=overlap@3≥0.33")
print("="*80)
