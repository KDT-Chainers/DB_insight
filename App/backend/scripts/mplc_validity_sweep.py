"""scripts/mplc_validity_sweep.py — MPLC keyword_count weight 종합 영향 평가.

다양한 쿼리 카테고리 × 두 weight 설정 (0 vs 원본 3.27) → top-5 결과 비교.
출력: stdout 표 + json 저장
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:5001/api/search"

QUERIES = [
    # 카테고리별 — (label, query)
    ("A1-구체단어", "고양이"),
    ("A2-구체단어", "강아지"),
    ("A3-구체단어", "햄버거"),
    ("A4-구체단어", "자동차"),
    ("A5-구체단어", "비행기"),
    ("B1-추상단어", "행복"),
    ("B2-추상단어", "평화"),
    ("B3-추상단어", "자연"),
    ("B4-추상단어", "풍경"),
    ("B5-추상단어", "추억"),
    ("C1-짧은구", "빨간 사과"),
    ("C2-짧은구", "눈 내리는 산"),
    ("C3-짧은구", "바다 일몰"),
    ("C4-짧은구", "도시 야경"),
    ("C5-짧은구", "박스 고양이"),
    ("D1-자연어", "박스 속에 들어있는 고양이"),
    ("D2-자연어", "햄버거를 먹는 사람"),
    ("D3-자연어", "노을 지는 해변"),
    ("D4-자연어", "벚꽃이 핀 거리"),
    ("D5-자연어", "공원에서 뛰어노는 어린이"),
    ("E1-영문", "cat"),
    ("E2-영문", "dog"),
    ("E3-영문", "hamburger"),
    ("E4-영문", "vintage car"),
    ("E5-영문", "modern building"),
    ("F1-거짓캡션", "사자"),
    ("F2-거짓캡션", "인형"),
    ("F3-거짓캡션", "박스"),
    ("G1-특이", "보이저호"),
    ("G2-특이", "코스모스"),
]

# 무관 매칭 식별용 — "고양이" 검색 시 사자상/강아지가 top 에 있으면 false positive
LION_FAMILY = {"real_cat_31", "real_cat_32", "real_cat_33"}
CAT_DOLL_FAMILY = {"cat_doll_34", "cat_doll_35"}


def search(query: str, top_k: int = 100, file_type: str = "image") -> dict:
    q = urllib.parse.quote(query)
    url = f"{API}?q={q}&top_k={top_k}&type={file_type}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def analyze(query: str) -> dict:
    res = search(query)
    items = res.get("results", [])
    n = len(items)
    if n == 0:
        return {"n": 0, "top_files": [], "lion_in_top10": False, "caption_misled_in_top10": 0}

    top10_names = [Path(it.get("file_name", "")).stem for it in items[:10]]
    lion_count = sum(1 for n_ in top10_names if n_ in LION_FAMILY)
    doll_count = sum(1 for n_ in top10_names if n_ in CAT_DOLL_FAMILY)

    top5 = []
    for it in items[:5]:
        top5.append({
            "name": it.get("file_name", "?"),
            "conf": round(float(it.get("confidence") or 0) * 100, 1),
            "dense": round(float(it.get("dense") or 0) * 100, 1),
            "rerank": round(float(it.get("rerank_score") or 0), 2)
                      if it.get("rerank_score") is not None else None,
            "visual": round(float(it.get("visual_match") or 0), 3)
                      if it.get("visual_match") is not None else None,
        })
    return {
        "n": n,
        "top5": top5,
        "lion_in_top10": lion_count > 0,
        "caption_misled_in_top10": lion_count + doll_count,
    }


def main():
    output: dict[str, dict] = {}
    print(f"=== {len(QUERIES)}개 쿼리 평가 시작 ===")
    t0 = time.time()
    for label, q in QUERIES:
        try:
            r = analyze(q)
            output[label] = {"query": q, **r}
            top1 = r["top5"][0]["name"] if r.get("top5") else "(0건)"
            top1_vm = r["top5"][0].get("visual") if r.get("top5") else None
            print(f"  {label:14s} '{q[:25]:25s}' n={r['n']:3d} top1={top1:35s} vm={top1_vm} misled={r['caption_misled_in_top10']}")
        except Exception as e:
            print(f"  {label}: ERROR {e}")
            output[label] = {"query": q, "error": str(e)}

    print(f"\n총 소요: {time.time()-t0:.1f}s")

    # JSON 저장
    out_path = Path(__file__).parent.parent / "scripts" / "mplc_sweep_result.json"
    if len(sys.argv) > 1:
        suffix = sys.argv[1]  # 예: "kc0" or "kc327"
        out_path = out_path.with_name(f"mplc_sweep_{suffix}.json")
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"저장: {out_path}")


if __name__ == "__main__":
    main()
