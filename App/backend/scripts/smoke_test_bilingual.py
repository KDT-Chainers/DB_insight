"""전 도메인 한↔영 이중언어 검색 스모크 테스트.
   앱을 재시작한 후 실행하거나, 직접 engine을 로드해서 실행.

   사용법:
     python _smoke_test_bilingual.py
"""
import sys, json, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from services.query_expand import expand_bilingual

# ── 테스트 케이스 정의 ────────────────────────────────────────────────
# (query_ko, query_en, expected_filenames_partial, domain, description)
TEST_CASES = [
    # ── MOVIE ──────────────────────────────────────────────────────
    ("코스모스", "cosmos", ["NGC 코스모스"], "movie",
     "NGC 코스모스 시리즈 전편 검색"),
    ("보이저 골든디스크", "voyager golden record", ["NGC 코스모스 E11"], "movie",
     "보이저 골든디스크 에피소드"),
    ("우주 탐사", "space exploration", ["NGC 코스모스", "인간과 우주"], "movie",
     "우주 탐사 다큐"),
    ("칼 세이건", "Carl Sagan", ["NGC 코스모스"], "movie",
     "칼 세이건(Carl Sagan) 이름 검색"),
    ("실크로드", "silk road", ["실크로드", "고선지"], "movie",
     "실크로드 시리즈"),
    ("인류 역사", "human history", ["인류", "글로벌 다큐"], "movie",
     "인류 역사 다큐"),
    ("외계인 찾기", "search for aliens", ["인간과 우주"], "movie",
     "외계 생명체 다큐"),
    # ── MUSIC/REC ───────────────────────────────────────────────────
    ("인공지능 뉴스", "AI news", ["AI뉴스", "박태웅"], "music",
     "AI 뉴스/팟캐스트"),
    ("박태웅 의장", "Park Taewung", ["박태웅"], "music",
     "박태웅 의장 강연"),
    ("클로드 코드", "Claude Code", ["Claude Code", "클로드"], "music",
     "Claude Code 강의"),
    # ── DOC (간단 확인) ─────────────────────────────────────────────
    # 실제 doc 파일명을 모르므로 키워드만 테스트
    ("경제", "economy", [], "doc", "경제 문서"),
    ("인공지능", "artificial intelligence", [], "doc", "AI 문서"),
]

print("=" * 70)
print("한↔영 이중언어 쿼리 확장 검증")
print("=" * 70)

for ko, en, expected, domain, desc in TEST_CASES:
    # 1) 쿼리 확장 확인
    ko_expanded = expand_bilingual(ko)
    en_expanded = expand_bilingual(en)

    ko_has_en = any(e.lower() in ko_expanded.lower() for e in en.split() if len(e) >= 3)
    en_has_ko = any(k in en_expanded for k in ko.split() if len(k) >= 2)

    print(f"\n[{domain.upper()}] {desc}")
    print(f"  KO '{ko}' → '{ko_expanded[:80]}'  (has EN: {'✓' if ko_has_en else '✗'})")
    print(f"  EN '{en}' → '{en_expanded[:80]}'  (has KO: {'✓' if en_has_ko else '✗'})")

print("\n" + "=" * 70)
print("엔진 로드 후 실제 검색 테스트")
print("=" * 70)

# 엔진 로드 시도
try:
    from routes.trichef import _get_engine
    engine = _get_engine()
    print(f"[엔진] 로드 성공")

    # 영화 테스트
    movie_tests = [
        ("코스모스", "movie", ["NGC 코스모스"], 13),
        ("cosmos", "movie", ["NGC 코스모스"], 5),
        ("보이저 골든디스크", "movie", ["E11"], 1),
        ("실크로드", "movie", ["실크로드", "고선지"], 5),
        ("voyager golden record", "movie", ["E11", "코스모스"], 1),
    ]

    for q, domain, expected_contains, expected_min in movie_tests:
        q_exp = expand_bilingual(q)
        t0 = time.time()
        results = engine.search_av(q_exp, domain=domain, topk=20)
        elapsed = time.time() - t0

        found_names = [r.file_name for r in results]
        matched = [fn for fn in found_names
                   if any(e.lower() in fn.lower() for e in expected_contains)]

        status = "✓" if len(matched) >= expected_min else "✗"
        print(f"\n  {status} '{q}' → {len(results)}건 ({elapsed*1000:.0f}ms)")
        for r in results[:5]:
            flag = "  ← MATCH" if any(e.lower() in r.file_name.lower() for e in expected_contains) else ""
            print(f"    [{r.confidence:.2f}] {r.file_name[:60]}{flag}")
        if len(matched) < expected_min:
            print(f"    ⚠ 예상: {expected_contains} {expected_min}건 이상, 실제: {len(matched)}건")

    # 음악 테스트
    print(f"\n  --- MUSIC/REC ---")
    music_tests = [
        ("박태웅", "music", ["박태웅"], 1),
        ("AI news", "music", ["AI뉴스", "AI"], 2),
        ("Claude Code", "music", ["Claude Code", "클로드"], 1),
    ]
    for q, domain, expected_contains, expected_min in music_tests:
        q_exp = expand_bilingual(q)
        results = engine.search_av(q_exp, domain=domain, topk=10)
        matched = [r for r in results
                   if any(e.lower() in r.file_name.lower() for e in expected_contains)]
        status = "✓" if len(matched) >= expected_min else "✗"
        print(f"  {status} '{q}' → {len(results)}건 | matched: {len(matched)}")
        for r in results[:3]:
            print(f"    [{r.confidence:.2f}] {r.file_name[:60]}")

except Exception as e:
    print(f"[엔진] 로드 실패: {e}")
    print("  → 앱 재시작 후 다시 실행하거나, API 서버가 실행 중인지 확인하세요.")

print(f"\n[완료] {time.strftime('%H:%M:%S')}")
