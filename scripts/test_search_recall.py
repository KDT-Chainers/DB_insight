"""검색 정확도 자동 검증 — 도메인별 정답 매핑 기반 recall@K 측정.

각 쿼리에 대해 "정답 파일명 패턴" 을 정의 → top-K 결과에 정답 패턴 일치 파일이
포함되는지 확인 → 도메인별 / 전체 recall@10 산출.

사용:
    python scripts/test_search_recall.py
    python scripts/test_search_recall.py --top-k 20

출력:
    [QUERY] "박태웅 의장"
        expected pattern: "박태웅"
        domains hit:      music: 7/10, video: 0/10, doc: 0/10, image: 0/10
        recall@10:        100% (7 expected found)
        duplicates:       0
        avg conf top-3:   0.987
"""
from __future__ import annotations

import argparse
import json
import sys
import io
import time
import urllib.parse
import urllib.request
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

API_BASE = "http://127.0.0.1:5001"

# 검증 케이스: (query, 정답 패턴, 정답 도메인 우선순위)
# 정답 패턴: 파일명에 포함되어야 하는 substring (대소문자 무시)
TEST_CASES = [
    # 음성 (Rec)
    {"q": "박태웅 의장",         "pat": "박태웅",         "expect_dom": "audio"},
    {"q": "AI 미토스",            "pat": "Mytho",          "expect_dom": "audio"},
    {"q": "장동혁 빈손",          "pat": "장동혁",         "expect_dom": "audio"},
    {"q": "김진태 빨간색",        "pat": "김진태",         "expect_dom": "audio"},
    {"q": "트럼프 이란",          "pat": "트럼프",         "expect_dom": "audio"},

    # 동영상 (Movie)
    {"q": "홍준표 김부겸",        "pat": "홍준표",         "expect_dom": "video"},
    {"q": "박덕흠 공관위",        "pat": "박덕흠",         "expect_dom": "video"},
    {"q": "농구 라이징이글스",    "pat": "라이징이글",     "expect_dom": "video"},
    {"q": "양자역학 범준",        "pat": "양자역학",       "expect_dom": "video"},
    {"q": "두산 삼성 야구",       "pat": "두산",           "expect_dom": "video"},

    # 이미지 (Img)
    {"q": "korean cafe",          "pat": "korean_cafe",    "expect_dom": "image"},
    {"q": "korean street",        "pat": "korean_street",  "expect_dom": "image"},
    {"q": "real apple",           "pat": "real_apple",     "expect_dom": "image"},
    {"q": "nature photo",         "pat": "nature",         "expect_dom": "image"},
    {"q": "real car",             "pat": "real_car",       "expect_dom": "image"},

    # 문서 (Doc)
    {"q": "AI 브리프",            "pat": "AI",             "expect_dom": "doc"},
    {"q": "SW 중심사회",          "pat": "SW",             "expect_dom": "doc"},
    {"q": "산업 연간 보고서",     "pat": "산업",           "expect_dom": "doc"},
    {"q": "주연 텍스트 샘플",     "pat": "주연",           "expect_dom": "doc"},
    {"q": "승인 통계 보고서",     "pat": "통계",           "expect_dom": "doc"},
]


def search(q: str, top_k: int = 10, dtype: str | None = None) -> dict:
    params = {"q": q, "top_k": top_k}
    if dtype:
        params["type"] = dtype
    url = f"{API_BASE}/api/search?" + urllib.parse.urlencode(params)
    t0 = time.time()
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read())
    data["_elapsed"] = time.time() - t0
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    # health check
    try:
        urllib.request.urlopen(f"{API_BASE}/api/health", timeout=3)
    except Exception:
        # try /api/files/stats
        try:
            urllib.request.urlopen(f"{API_BASE}/api/files/stats", timeout=3)
        except Exception as e:
            print(f"[ERROR] 백엔드({API_BASE}) 응답 없음: {e}")
            return 2

    overall_hits  = 0
    overall_total = 0
    domain_recall = Counter()
    domain_total  = Counter()
    elapsed_sum   = 0.0
    dup_total     = 0
    confs_topk    = []

    print(f"\n=== 검색 정확도 검증 (top-{args.top_k}) ===\n")
    print(f"{'#':<3} {'쿼리':<25} {'정답패턴':<18} {'예상도메인':<8} "
          f"{'recall':<10} {'중복':<6} {'평균conf':<10} {'경과':<8}")
    print("-" * 100)

    for i, case in enumerate(TEST_CASES, 1):
        q   = case["q"]
        pat = case["pat"].lower()
        exp = case["expect_dom"]
        try:
            data = search(q, args.top_k)
        except Exception as e:
            print(f"{i:<3} {q:<25} ERROR: {e}")
            continue

        results = data.get("results", [])
        elapsed = data.get("_elapsed", 0)
        elapsed_sum += elapsed

        # recall: top-K 안에 정답 패턴 포함 파일 수
        hits = [r for r in results if pat in (r.get("file_name") or "").lower()]
        n_hits = len(hits)

        # 중복 (file_name 같은 결과 카운트)
        fname_count = Counter((r.get("file_name") or "").lower() for r in results)
        dups = sum(c - 1 for c in fname_count.values() if c > 1)
        dup_total += dups

        # avg conf top-3
        confs = [float(r.get("confidence", 0) or 0) for r in results[:3]]
        avg_conf = sum(confs) / max(len(confs), 1)
        confs_topk.append(avg_conf)

        # 도메인 분포 — 정답 도메인 hit
        exp_hits = sum(1 for r in hits if (r.get("file_type") or "") == exp)
        domain_recall[exp] += exp_hits
        domain_total[exp]  += 1

        if n_hits > 0:
            overall_hits += 1
        overall_total += 1

        recall_pct = n_hits / max(args.top_k, 1) * 100
        recall_str = f"{n_hits}/{args.top_k} ({recall_pct:.0f}%)"

        print(f"{i:<3} {q:<25} {case['pat']:<18} {exp:<8} "
              f"{recall_str:<10} {dups:<6} {avg_conf:<10.3f} {elapsed:.2f}s")

    # 요약
    print("\n" + "=" * 100)
    print("요약")
    print("=" * 100)
    print(f"  총 쿼리:               {overall_total}")
    print(f"  최소 1건 정답 발견:    {overall_hits} ({overall_hits/overall_total*100:.0f}%)")
    print(f"  중복 결과 합계:        {dup_total}")
    print(f"  평균 응답 시간:        {elapsed_sum/overall_total:.2f}s")
    print(f"  평균 conf (top-3):     {sum(confs_topk)/len(confs_topk):.3f}")
    print()
    print("  도메인별 expected-hit recall:")
    for dom in ("audio", "video", "image", "doc"):
        n = domain_recall.get(dom, 0)
        t = domain_total.get(dom, 0)
        if t > 0:
            print(f"    {dom:<6}: {n} expected-domain hits in {t} queries")

    return 0


if __name__ == "__main__":
    sys.exit(main())
