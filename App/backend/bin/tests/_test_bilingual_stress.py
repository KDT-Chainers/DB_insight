"""
Bilingual STRESS TEST — broader domain coverage with harder query pairs.
Tests Korean↔English cross-lingual search for edge-case vocabulary.
Pass threshold: overlap@3 >= 0.20 (looser than main test 0.33)
"""
from __future__ import annotations
import sys, io, time
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TOP_K = 5
THRESHOLD = 0.20   # looser threshold for stress test

# ── Stress pairs: (ko_query, en_query, label, domains) ─────────────────────
PAIRS = [
    # movie — news/social topics
    ("코로나 방역 팬데믹",       "COVID pandemic prevention",        "covid_movie",   ["movie"]),
    ("부동산 아파트 집값",       "real estate housing prices",       "housing_movie", ["movie"]),
    ("환경 기후변화 탄소중립",   "climate change carbon neutral",    "climate_movie", ["movie"]),
    ("의료 병원 수술",          "medical hospital surgery",         "medical_movie", ["movie"]),
    ("교육 학교 학생",          "education school student",         "edu_movie",     ["movie"]),
    ("경찰 수사 범죄",          "police investigation crime",       "crime_movie",   ["movie"]),
    ("홍수 태풍 재난",          "flood typhoon disaster",           "disaster_movie",["movie"]),
    ("취업 구직 일자리",        "employment job career",            "job_movie",     ["movie"]),
    # music
    ("코로나 방역",             "COVID pandemic",                   "covid_music",   ["music"]),
    ("경제 뉴스 주식",          "economy news stock",               "economy_music", ["music"]),
    ("기술 AI 로봇",            "technology AI robot",              "tech_music",    ["music"]),
    # BGM
    ("슬픈 감성 음악",          "sad emotional melancholic music",  "sad_bgm",       ["bgm"]),
    ("자연 새소리 바람",        "nature birds wind ambient",        "nature_bgm",    ["bgm"]),
    ("영화음악 오케스트라",     "orchestral cinematic epic",        "filmscore_bgm", ["bgm"]),
    # image
    ("나무 숲 자연",            "tree forest nature",               "forest_img",    ["image"]),
    ("자동차 도로 차",          "car road vehicle",                 "car_img",       ["image"]),
    ("야경 밤하늘 도시",        "night city skyline",               "nightcity_img", ["image"]),
    ("사람 군중 거리",          "people crowd street",              "crowd_img",     ["image"]),
    # new additions
    ("웹툰 만화 만화책",        "webtoon manhwa comic",             "webtoon_movie", ["movie"]),
    ("결혼 이혼 가정",          "marriage divorce family",          "family_movie",  ["movie"]),
    ("비만 당뇨 고혈압",        "obesity diabetes hypertension",    "health_movie",  ["movie"]),
    ("유튜브 영상 채널",        "youtube video channel",            "youtube_movie", ["movie"]),
]

def overlap_at_k(a: list[str], b: list[str], k: int = 3) -> float:
    sa, sb = set(a[:k]), set(b[:k])
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)

def short(s: str, n: int = 55) -> str:
    name = s.split("/")[-1].split("\\")[-1]
    return name[:n] + ("…" if len(name) > n else "")


# ── Load engines ──────────────────────────────────────────────────────────
print("Loading engines…", flush=True)
t0 = time.time()
from services.trichef.unified_engine import TriChefEngine
engine = TriChefEngine()

from services.bgm.search_engine import get_engine as get_bgm
bgm = get_bgm()
bgm._ensure_loaded()
print(f"  ready in {time.time()-t0:.1f}s\n")

from services.query_expand import expand_bilingual as _ebil

# ── Run tests ─────────────────────────────────────────────────────────────
total = 0
passed = 0
fails = []

for ko_q, en_q, label, domains in PAIRS:
    for domain in domains:
        total += 1
        try:
            if domain == "bgm":
                r_ko = bgm.search(ko_q, top_k=TOP_K)["results"]
                r_en = bgm.search(en_q, top_k=TOP_K)["results"]
                ko_fns = [r["filename"] for r in r_ko]
                en_fns = [r["filename"] for r in r_en]
            elif domain in ("image", "doc_page"):
                ko_exp = _ebil(ko_q)
                en_exp = _ebil(en_q)
                r_ko = engine.search(ko_exp, domain=domain, topk=TOP_K,
                                     use_lexical=True, use_asf=True)
                r_en = engine.search(en_exp, domain=domain, topk=TOP_K,
                                     use_lexical=True, use_asf=True)
                def _dk(rid):
                    p = rid.replace("\\", "/").split("/")
                    return p[1] if len(p) >= 3 else rid
                if domain == "doc_page":
                    ko_fns = [_dk(r.id) for r in r_ko]
                    en_fns = [_dk(r.id) for r in r_en]
                else:
                    ko_fns = [r.id for r in r_ko]
                    en_fns = [r.id for r in r_en]
            else:
                r_ko = engine.search_av(ko_q, domain=domain, topk=TOP_K)
                r_en = engine.search_av(en_q, domain=domain, topk=TOP_K)
                ko_fns = [r.file_name for r in r_ko]
                en_fns = [r.file_name for r in r_en]

            ov = overlap_at_k(ko_fns, en_fns, k=3)
            ok = ov >= THRESHOLD
            if ok:
                passed += 1
                status = "PASS"
            else:
                fails.append((domain, label, ov, ko_q, en_q))
                status = "FAIL"
            print(f"[{domain}] {status} ov={ov:.2f}  '{ko_q}'")

        except Exception as e:
            print(f"[{domain}] ERROR  '{ko_q}': {e}")
            fails.append((domain, label, -1, ko_q, en_q))

print(f"\nSTRESS TEST: {passed}/{total} passed")
if fails:
    print("FAILS:")
    for domain, label, ov, ko, en in fails:
        print(f"  [{domain}] ov={ov:.2f}  '{ko}' vs '{en}'")
