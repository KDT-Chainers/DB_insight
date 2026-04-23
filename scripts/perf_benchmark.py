"""scripts/perf_benchmark.py — 파이프라인 성능/품질 벤치마크.

측정:
1. 엔진 초기화 시간 + 메모리
2. 쿼리별 latency (cold/warm), 채널별 시간
3. 3채널 기여도 (top-K 변화율)
4. 신규 hwp/hwpx 콘텐츠 검색 가능성 (한글 쿼리 recall proxy)
"""
from __future__ import annotations

import gc
import json
import os
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def rss_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024


def main():
    proc = psutil.Process(os.getpid())
    print("="*70)
    print("1. 엔진 초기화")
    print("="*70)
    rss0 = rss_mb()
    t0 = time.perf_counter()
    from services.trichef.unified_engine import TriChefEngine
    eng = TriChefEngine()
    dt_init = time.perf_counter() - t0
    rss1 = rss_mb()
    print(f"init: {dt_init:.2f}s  RSS: {rss0:.0f} → {rss1:.0f} MB (+{rss1-rss0:.0f})")
    for dom, d in eng._cache.items():
        print(f"  {dom}: Re{d['Re'].shape}  sparse{d['sparse'].shape}  asf_sets={len(d['asf_sets'])}  vocab={len(d['vocab'])}")

    print("\n" + "="*70)
    print("2. 쿼리 latency (cold + warm × 3)")
    print("="*70)
    queries = [
        ("doc_page", "환경 정책"),
        ("doc_page", "재난환경 변화 재난관리"),    # hwp/hwpx 콘텐츠
        ("doc_page", "지역금융 사회연대"),        # hwp/hwpx 콘텐츠
        ("doc_page", "인공지능 교육"),
        ("doc_page", "탄소중립"),
        ("image", "사람 얼굴"),
    ]
    all_lat: list[float] = []
    for dom, q in queries:
        times = []
        for i in range(3):
            t = time.perf_counter()
            res = eng.search(q, domain=dom, topk=10, use_lexical=True, use_asf=True)
            times.append(time.perf_counter() - t)
        all_lat.extend(times)
        print(f"  {dom:9s} '{q}': cold={times[0]*1000:.0f}ms  "
              f"warm={sum(times[1:])/2*1000:.0f}ms  returned={len(res)}")
    print(f"  avg warm: {np.mean(all_lat[1::3])*1000:.0f}ms  "
          f"p50={np.percentile(all_lat,50)*1000:.0f}ms  "
          f"p95={np.percentile(all_lat,95)*1000:.0f}ms")

    print("\n" + "="*70)
    print("3. 3채널 기여도 (top-10 overlap)")
    print("="*70)
    CFGS = [
        ("dense",        dict(use_lexical=False, use_asf=False)),
        ("+sparse",      dict(use_lexical=True,  use_asf=False)),
        ("+sparse+asf",  dict(use_lexical=True,  use_asf=True)),
    ]
    for dom, q in queries:
        tops = {}
        for name, cfg in CFGS:
            r = eng.search(q, domain=dom, topk=10, **cfg)
            tops[name] = [x.id for x in r]
        d  = set(tops["dense"])
        ds = set(tops["+sparse"])
        da = set(tops["+sparse+asf"])
        print(f"  {dom:9s} '{q}': "
              f"|d∩+sp|={len(d&ds):>2}  |d∩+asf|={len(d&da):>2}  "
              f"|Δ asf↔+sp|={len(ds.symmetric_difference(da)):>2}")

    print("\n" + "="*70)
    print("4. 신규 hwp/hwpx 콘텐츠 검색 가능성")
    print("="*70)
    hwp_queries = [
        "재난환경 변화 대응",
        "지역금융 사회연대 소멸",
        "환경부 캠핑장 쓰레기",
        "기후변화 탄소중립 건물",
        "인공지능 환경단체",
    ]
    hwp_hits = 0
    for q in hwp_queries:
        r = eng.search(q, domain="doc_page", topk=10)
        # hwp/hwpx 소스는 'text_samples_주연_2차' 디렉토리 아래
        hwp_topk = [x for x in r if "text_samples" in x.id]
        hit = len(hwp_topk) > 0
        hwp_hits += int(hit)
        print(f"  '{q}': total={len(r)}  hwp_hit={len(hwp_topk)}  "
              + (f"top={hwp_topk[0].id[:60]}" if hwp_topk else ""))
    print(f"  hwp coverage: {hwp_hits}/{len(hwp_queries)} 쿼리에서 hwp 결과 등장")

    print("\n" + "="*70)
    print("5. 최종 RSS")
    print("="*70)
    print(f"  RSS after bench: {rss_mb():.0f} MB  peak {proc.memory_info().peak_wset/1024/1024:.0f} MB"
          if hasattr(proc.memory_info(), 'peak_wset') else f"  RSS: {rss_mb():.0f} MB")


if __name__ == "__main__":
    main()
