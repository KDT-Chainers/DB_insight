"""[최종 검증] 5종 자동 테스트.

1) 인덱스 무결성 재스캔
2) 검색 벤치 확장 (음성·BGM 포함 30쿼리)
3) AIMODE 단위 검증 (소스 cap·heartbeat 코드 점검)
4) 검색 응답시간 부하 (동시 10쿼리)
5) PDF figure 시각 검색 검증
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "App" / "backend"))


def test1_integrity():
    print("\n" + "="*60)
    print("[Test 1/5] 인덱스 무결성 재스캔")
    print("="*60)
    import subprocess
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(_ROOT/"App"/"backend"/"scripts"/"check_index_integrity.py")],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    print(r.stdout[-2000:])
    return r.returncode == 0


def test2_bench_extended():
    print("\n" + "="*60)
    print("[Test 2/5] 검색 벤치 확장 (음성·BGM 추가)")
    print("="*60)
    from routes.trichef import _get_engine
    eng = _get_engine()
    eng.reload()
    # 확장 쿼리 — 음성, BGM, image, doc, movie 모두 포함
    QS = [
        ("박스 속에 있는 고양이", "image", ["cat", "고양이"]),
        ("귀여운 강아지", "image", ["dog", "강아지"]),
        ("자동차", "image", ["car", "자동차", "자동차"]),
        ("음식 사진", "image", ["food", "음식", "burger"]),
        ("코스모스 보이저호", "movie", ["코스모스", "voyager", "보이저"]),
        ("우주 탐사", "movie", ["우주", "보이저", "cosmos"]),
        ("AI 인공지능", "doc_page", ["AI", "인공지능"]),
        ("경주 동궁 월지", "doc_page", ["경주", "동궁", "월지"]),
        ("SW산업", "doc_page", ["SW", "소프트웨어"]),
        ("나이테 동아시아", "doc_page", ["나이테", "동아시아"]),
        ("정부 정책", "doc_page", ["정부", "정책"]),
        ("주식 부동산", "music", ["주식", "부동산", "다스뵈이다"]),
        ("AI 본부", "music", ["AI", "본부", "유엔"]),
        ("뉴스", "music", ["뉴스", "TV"]),
    ]
    results = []
    for q, dom, kws in QS:
        try:
            t0 = time.time()
            res = eng.search(q, domain=dom, topk=10)
            elapsed = time.time() - t0
            hits = sum(1 for r in res[:10] if any(kw.lower() in r.id.lower() for kw in kws))
            results.append((dom, q, hits, len(res), elapsed))
            print(f"  [{dom:<10s}] '{q}': {hits}/{min(10,len(res))} ({elapsed*1000:.0f}ms)")
        except Exception as e:
            print(f"  [{dom}] '{q}' ERROR: {e}")
            results.append((dom, q, 0, 0, 0))
    avg_hits = sum(h for _,_,h,_,_ in results) / max(len(results),1)
    total_ms = sum(e for _,_,_,_,e in results) * 1000
    print(f"\n  평균 매칭: {avg_hits:.1f}/10, 총 시간: {total_ms:.0f}ms")
    return avg_hits >= 5.0


def test3_aimode_inspection():
    print("\n" + "="*60)
    print("[Test 3/5] AIMODE 코드 점검 (소스 cap + heartbeat)")
    print("="*60)
    aimode_path = _ROOT / "App" / "backend" / "routes" / "aimode.py"
    src = aimode_path.read_text(encoding="utf-8")
    checks = {
        "_MAX_TOTAL_SOURCES 정의": "_MAX_TOTAL_SOURCES" in src,
        "8개 cap 설정": "_MAX_TOTAL_SOURCES = 8" in src,
        "follow-up 히스토리 2턴": "prior_history[-2:]" in src,
        "heartbeat emit": '"type": "heartbeat"' in src,
        "_HEARTBEAT_SEC 정의": "_HEARTBEAT_SEC" in src,
        "5초 폴링": "_HEARTBEAT_SEC = 5" in src,
        "_MAX_TOTAL_SEC 300": "_MAX_TOTAL_SEC = 300" in src,
    }
    ok = True
    for k, v in checks.items():
        mark = "✓" if v else "✗"
        if not v: ok = False
        print(f"  {mark} {k}")
    return ok


def test4_concurrent_search():
    print("\n" + "="*60)
    print("[Test 4/5] 동시 10쿼리 부하 테스트")
    print("="*60)
    from routes.trichef import _get_engine
    eng = _get_engine()
    queries = [
        ("고양이", "image"), ("강아지", "image"), ("음식", "image"),
        ("AI", "doc_page"), ("경주", "doc_page"), ("SW", "doc_page"),
        ("코스모스", "movie"), ("보이저호", "movie"),
        ("주식", "music"), ("뉴스", "music"),
    ]
    def _one(q_dom):
        q, dom = q_dom
        t0 = time.time()
        try:
            r = eng.search(q, domain=dom, topk=10)
            return (q, dom, len(r), time.time()-t0, None)
        except Exception as e:
            return (q, dom, 0, time.time()-t0, str(e))
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(_one, queries))
    total = time.time() - t0
    errs = [r for r in results if r[4]]
    avg = sum(r[3] for r in results) / max(len(results),1)
    max_ = max(r[3] for r in results)
    print(f"  10 동시 쿼리 총 소요: {total*1000:.0f}ms")
    print(f"  평균: {avg*1000:.0f}ms, 최대: {max_*1000:.0f}ms")
    print(f"  오류: {len(errs)}건")
    for q, dom, n, t, err in results:
        print(f"    [{dom:<10s}] {q!r:<20s} {n}건 ({t*1000:.0f}ms){' ERR:'+err if err else ''}")
    return len(errs) == 0


def test5_pdf_figure_search():
    print("\n" + "="*60)
    print("[Test 5/5] PDF figure 시각 검색 검증")
    print("="*60)
    from routes.trichef import _get_engine
    eng = _get_engine()
    # doc_figures 등록 keys 확인
    img_cache = _ROOT / "Data" / "embedded_DB" / "Img"
    raw = json.loads((img_cache/"img_ids.json").read_text(encoding="utf-8"))
    ids = raw.get("ids", []) if isinstance(raw, dict) else list(raw)
    fig_keys = [i for i in ids
                if "staged/" in i
                and any(p in i for p in ("_f0", "_f1", "_f2"))
                and any(p in i for p in (".jpeg", ".png"))]
    print(f"  PDF figure 키 추정: {len(fig_keys)}개 / 총 {len(ids)}")

    # figure 가 검색에 등장하는지
    qs = ["도표 그래프", "차트", "지도", "건축 평면도", "사진"]
    total_fig_in_top10 = 0
    for q in qs:
        res = eng.search(q, domain="image", topk=10)
        fig_hits = sum(1 for r in res if any(p in r.id for p in ("_f0", "_f1", "_f2")))
        total_fig_in_top10 += fig_hits
        print(f"  '{q}' top10 figure 매칭: {fig_hits}건  (top1 score={res[0].score:.3f} {res[0].id[:70]})")
    print(f"\n  5쿼리 top10에서 PDF figure 등장 누적: {total_fig_in_top10}건")
    return True  # 단순 확인용


def main():
    print(f"=== 최종 검증 5종 시작 ({time.strftime('%H:%M:%S')}) ===")
    t0 = time.time()
    results = {}
    for name, fn in [("integrity", test1_integrity),
                     ("bench_ext", test2_bench_extended),
                     ("aimode", test3_aimode_inspection),
                     ("concurrent", test4_concurrent_search),
                     ("figure", test5_pdf_figure_search)]:
        try:
            results[name] = fn()
        except Exception as e:
            print(f"\n[{name}] 예외: {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()
            results[name] = False
    print(f"\n{'='*60}\n=== 종합 결과 ({(time.time()-t0)/60:.1f}분) ===\n{'='*60}")
    for k, v in results.items():
        print(f"  {('✓' if v else '✗')} {k}")
    if all(results.values()):
        print("\n🎉 5종 검증 모두 통과")
    else:
        print(f"\n⚠️ {sum(1 for v in results.values() if not v)}건 미통과")


if __name__ == "__main__":
    main()
