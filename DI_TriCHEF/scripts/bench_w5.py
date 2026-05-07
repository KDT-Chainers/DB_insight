"""bench_w5.py — W5-1 전/후 비교용 고정 쿼리 벤치."""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request

QUERIES = [
    "강아지", "웃는 아이", "파란 하늘과 구름",
    "회의실 사진", "프로젝트 로고", "커피 한 잔",
    "가족 여행 사진", "눈 덮인 산", "도시 야경",
    "해변의 일몰", "운동하는 사람", "책상 위의 노트북",
    "음식 메뉴판", "도표와 그래프", "지도 이미지",
]

URL = "http://127.0.0.1:5001/api/trichef/search"


def one(query: str, domain: str = "image", topk: int = 10) -> tuple[float, float, int]:
    body = json.dumps({"query": query, "domain": domain, "topk": topk}).encode("utf-8")
    req = urllib.request.Request(URL, data=body,
                                  headers={"Content-Type": "application/json"})
    t = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
    dt = (time.time() - t) * 1000
    top = r.get("top", [])
    hits = [t for t in top if t.get("domain") == domain]
    conf = hits[0]["confidence"] if hits else 0.0
    return dt, conf, len(hits)


DOC_QUERIES = ["강아지", "프로젝트 관리", "SW 산업", "회의실"]


def main(regression: bool = False) -> int:
    lat: list[float] = []
    confs: list[float] = []
    hits: list[int] = []
    print(f"{'query':<20} {'lat_ms':>8} {'conf':>6} {'hits':>5}")
    for q in QUERIES:
        try:
            dt, c, n = one(q)
        except Exception as e:
            print(f"{q:<20} ERR {e}")
            continue
        lat.append(dt)
        confs.append(c)
        hits.append(n)
        print(f"{q:<20} {dt:>8.1f} {c:>6.3f} {n:>5d}")
    lat.sort()
    p50 = statistics.median(lat)
    p95 = lat[int(len(lat) * 0.95) - 1] if len(lat) >= 2 else lat[-1]
    top1_90 = sum(1 for c in confs if c >= 0.90) / len(confs) * 100
    print("---")
    print(f"p50={p50:.1f}ms  p95={p95:.1f}ms  "
          f"mean_conf={statistics.mean(confs):.3f}  "
          f"top1>=0.90: {top1_90:.0f}%  "
          f"avg_hits={statistics.mean(hits):.1f}")

    if not regression:
        return 0

    # ── regression 게이트 ──────────────────────────────────────
    #   1. p95 <= 250ms
    #   2. mean_conf >= 0.40
    #   3. doc_page 쿼리 4개 모두 hits > 0
    print("\n[regression] doc_page zero-hit 검사 ...")
    doc_zero = []
    for q in DOC_QUERIES:
        try:
            _, _, n = one(q, domain="doc_page", topk=5)
        except Exception as e:
            print(f"  {q}: ERR {e}"); doc_zero.append(q); continue
        mark = "[OK]" if n > 0 else "[!!]"
        print(f"  {mark} {q}: hits={n}")
        if n == 0:
            doc_zero.append(q)

    fail = []
    if p95 > 250: fail.append(f"p95 {p95:.0f}ms > 250ms")
    if statistics.mean(confs) < 0.40: fail.append(f"mean_conf {statistics.mean(confs):.3f} < 0.40")
    if doc_zero: fail.append(f"doc_page zero-hit: {doc_zero}")

    if fail:
        print(f"\n[regression] FAIL: {'; '.join(fail)}")
        return 1
    print("\n[regression] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(regression="--regression" in sys.argv))
