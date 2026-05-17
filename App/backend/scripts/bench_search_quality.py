"""[D-3] 검색 품질 회귀 벤치.

기준 쿼리에 대해 top-K 결과를 기록하고, 이전 결과(baseline)와 비교.
P1~P5 + Phase B~E 작업 전후의 검색 품질 변화를 정량 측정.

사용:
  python bench_search_quality.py --save baseline   # 베이스라인 저장
  python bench_search_quality.py --compare baseline # 베이스라인과 비교
  python bench_search_quality.py --list             # 쿼리 목록만
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "App" / "backend"))

# ── 기준 쿼리셋 ─────────────────────────────────────────────────────────
QUERIES = [
    # (query, domain, topk, expected_keyword[리스트] — 정답 후보 식별용)
    ("박스 속에 있는 고양이", "image", 10, ["cat", "고양이"]),
    ("햄버거", "image", 10, ["burger", "햄버거", "맥치킨", "food"]),
    ("귀여운 강아지", "image", 10, ["dog", "강아지", "puppy"]),
    ("눈 오는 풍경", "image", 10, ["snow", "winter", "겨울"]),
    ("코스모스 보이저호", "movie", 10, ["코스모스", "voyager", "보이저"]),
    ("보이저호", "movie", 10, ["voyager", "보이저", "코스모스"]),
    ("우주 다큐멘터리", "movie", 10, ["우주", "다큐", "cosmos"]),
    ("SW산업 인력", "doc_page", 10, ["SW", "소프트웨어", "인력"]),
    ("SW산업 동향", "doc_page", 10, ["SW", "소프트웨어", "동향"]),
    ("경주 동궁 월지", "doc_page", 10, ["경주", "동궁", "월지"]),
    ("나이테 동아시아", "doc_page", 10, ["나이테", "동아시아", "고기후"]),
    ("자기소개서 작성", "doc_page", 10, ["자기소개서", "취업"]),
    ("AI 인공지능", "doc_page", 10, ["AI", "인공지능"]),
]


def _run_bench(eng, queries):
    results = {}
    for q, dom, k, _ in queries:
        try:
            t0 = time.time()
            r = eng.search(q, domain=dom, topk=k)
            elapsed = time.time() - t0
            results[f"{dom}::{q}"] = {
                "elapsed": round(elapsed, 3),
                "results": [
                    {"rank": i + 1, "id": x.id, "score": round(float(x.score), 4)}
                    for i, x in enumerate(r)
                ],
            }
        except Exception as e:
            results[f"{dom}::{q}"] = {"error": str(e)}
    return results


def _score_match(result_ids: list[str], keywords: list[str]) -> int:
    """top10 중 keyword 매칭되는 결과 수 — relevance 휴리스틱."""
    hits = 0
    for rid in result_ids[:10]:
        low = rid.lower()
        if any(kw.lower() in low for kw in keywords):
            hits += 1
    return hits


def cmd_save(name: str):
    from routes.trichef import _get_engine
    eng = _get_engine()
    eng.reload()
    print(f"=== 벤치 저장: {name} ===")
    res = _run_bench(eng, QUERIES)
    out = _ROOT / "Data" / f"_bench_{name}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {len(res)}개 쿼리, 저장: {out}")
    for (q, dom, k, kws) in QUERIES:
        key = f"{dom}::{q}"
        if key in res and "results" in res[key]:
            hits = _score_match([r["id"] for r in res[key]["results"]], kws)
            print(f"  [{dom}] {q!r}: top{k} 키워드 매칭 {hits}/{k}  ({res[key]['elapsed']}s)")


def cmd_compare(name: str):
    from routes.trichef import _get_engine
    base_path = _ROOT / "Data" / f"_bench_{name}.json"
    if not base_path.exists():
        print(f"[error] 베이스라인 없음: {base_path}")
        sys.exit(1)
    base = json.loads(base_path.read_text(encoding="utf-8"))

    eng = _get_engine()
    eng.reload()
    cur = _run_bench(eng, QUERIES)

    print(f"=== 베이스라인({name}) vs 현재 ===")
    improved = degraded = same = 0
    for (q, dom, k, kws) in QUERIES:
        key = f"{dom}::{q}"
        if key not in base or "results" not in base[key] or "results" not in cur[key]:
            continue
        base_ids = [r["id"] for r in base[key]["results"]]
        cur_ids = [r["id"] for r in cur[key]["results"]]
        base_hits = _score_match(base_ids, kws)
        cur_hits = _score_match(cur_ids, kws)
        diff = cur_hits - base_hits
        mark = "▲" if diff > 0 else ("▼" if diff < 0 else "=")
        if diff > 0: improved += 1
        elif diff < 0: degraded += 1
        else: same += 1
        print(f"  {mark} [{dom}] {q!r}: {base_hits} → {cur_hits} (Δ{diff:+d})")
    print(f"\n  요약: 개선 {improved} · 유지 {same} · 저하 {degraded}")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--save", help="베이스라인 이름")
    g.add_argument("--compare", help="비교 대상 베이스라인 이름")
    g.add_argument("--list", action="store_true", help="쿼리 목록만 출력")
    args = ap.parse_args()

    if args.list:
        for q, dom, k, kws in QUERIES:
            print(f"  [{dom}] {q!r} (top{k}) — keywords={kws}")
        return
    if args.save:
        cmd_save(args.save)
    if args.compare:
        cmd_compare(args.compare)


if __name__ == "__main__":
    main()
