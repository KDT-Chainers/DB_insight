"""bench_av.py — Movie/Music AV 전용 regression 벤치.

게이트:
  1. music 쿼리 5개 모두 hits > 0
  2. top1 confidence >= 0.5
  3. p95 <= 2000ms (AV 는 BGE-M3 inference 1회 포함)
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request

URL_SEARCH   = "http://127.0.0.1:5001/api/trichef/search"
URL_INSPECT  = "http://127.0.0.1:5001/api/admin/inspect_av"

MUSIC_QUERIES = [
    "공부 방법",
    "학생 상담",
    "AI SaaS 창업",
    "Discord 봇",
    "교수님 답변",
]


def one(query: str, domain: str = "music", topk: int = 5) -> tuple[float, float, int]:
    body = json.dumps({"query": query, "domains": [domain],
                       "topk": topk, "top_segments": 3}).encode("utf-8")
    req = urllib.request.Request(URL_SEARCH, data=body,
                                  headers={"Content-Type": "application/json"})
    t = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
    dt = (time.time() - t) * 1000
    top = r.get("top", [])
    hits = [t for t in top if t.get("domain") == domain]
    conf = hits[0].get("confidence", 0.0) if hits else 0.0
    return dt, conf, len(hits)


def admin_one(query: str, domain: str = "music", top_n: int = 5):
    body = json.dumps({"query": query, "domain": domain,
                       "top_n": top_n, "top_segments": 3}).encode("utf-8")
    req = urllib.request.Request(URL_INSPECT, data=body,
                                  headers={"Content-Type": "application/json"})
    t = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
    dt = (time.time() - t) * 1000
    files = r.get("files", [])
    return dt, files, r.get("calibration", {})


def main(regression: bool = False) -> int:
    lat: list[float] = []
    confs: list[float] = []
    hits_list: list[int] = []
    zero = []
    print(f"[search]  {'query':<20} {'lat_ms':>8} {'conf':>6} {'hits':>5}")
    for q in MUSIC_QUERIES:
        try:
            dt, c, n = one(q)
        except Exception as e:
            print(f"  {q:<20} ERR {e}")
            zero.append(q); continue
        lat.append(dt); confs.append(c); hits_list.append(n)
        mark = "[OK]" if n > 0 else "[!!]"
        print(f"  {mark} {q:<20} {dt:>8.1f} {c:>6.3f} {n:>5d}")
        if n == 0: zero.append(q)

    lat_sorted = sorted(lat)
    p50 = statistics.median(lat_sorted) if lat_sorted else 0
    p95 = lat_sorted[int(len(lat_sorted)*0.95) - 1] if len(lat_sorted) >= 2 else (lat_sorted[-1] if lat_sorted else 0)
    mean_c = statistics.mean(confs) if confs else 0
    print("---")
    print(f"p50={p50:.1f}ms  p95={p95:.1f}ms  mean_conf={mean_c:.3f}  zero_hits={len(zero)}")

    # admin inspect_av 검증 (첫 쿼리만)
    print("\n[inspect_av] 관리자 API 동작 점검 ...")
    try:
        dt, files, cal = admin_one(MUSIC_QUERIES[0])
        print(f"  {MUSIC_QUERIES[0]}: {dt:.1f}ms, files={len(files)}, cal={cal}")
        if files:
            top = files[0]
            print(f"  top1: {top['file_name']}  score={top['score']}  conf={top['confidence']}")
            print(f"  segments={len(top.get('segments',[]))}")
    except Exception as e:
        print(f"  ERR {e}")
        if regression: return 1

    if not regression:
        return 0

    fail = []
    if zero: fail.append(f"zero_hits {zero}")
    if mean_c < 0.5: fail.append(f"mean_conf {mean_c:.3f} < 0.5")
    if p95 > 2000: fail.append(f"p95 {p95:.0f}ms > 2000ms")

    if fail:
        print(f"\n[regression] FAIL: {'; '.join(fail)}")
        return 1
    print("\n[regression] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(regression="--regression" in sys.argv))
