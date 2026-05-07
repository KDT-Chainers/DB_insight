"""bench_rerank.py — /api/admin/inspect 에 use_rerank 전/후 Top-10 비교."""
from __future__ import annotations

import json
import time
import urllib.request

URL = "http://127.0.0.1:5001/api/admin/inspect"

QUERIES = [
    ("강아지", "image"),
    ("회의실 책상", "image"),
    ("프로젝트 관리", "doc_page"),
]


def call(q: str, dom: str, rerank: bool) -> tuple[float, list[dict]]:
    body = {
        "query": q, "domain": dom, "top_n": 20,
        "use_lexical": True, "use_asf": True,
        "use_rerank": rerank, "rerank_k": 20,
    }
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    t = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=120).read().decode("utf-8"))
    return (time.time() - t) * 1000, r["rows"]


def main() -> None:
    for q, dom in QUERIES:
        print(f"\n=== [{dom}] {q} ===")
        dt0, rows0 = call(q, dom, False)
        print(f"BASE   {dt0:.0f}ms  top5: " +
              ", ".join(f"{r['filename'][:20]}(f={r['fused']:.2f})" for r in rows0[:5]))
        try:
            dt1, rows1 = call(q, dom, True)
        except Exception as e:
            print(f"RERANK ERR: {e}")
            continue
        print(f"RERANK {dt1:.0f}ms  top5: " +
              ", ".join(f"{r['filename'][:20]}(rr={r.get('rerank','-'):.2f})"
                        if isinstance(r.get("rerank"), (int, float))
                        else f"{r['filename'][:20]}(rr=-)"
                        for r in rows1[:5]))

        # 순위 변동 측정
        id_rank0 = {r["id"]: i for i, r in enumerate(rows0[:10])}
        id_rank1 = {r["id"]: i for i, r in enumerate(rows1[:10])}
        common = set(id_rank0) & set(id_rank1)
        if common:
            shifts = [abs(id_rank0[i] - id_rank1[i]) for i in common]
            print(f"       Top-10 평균 rank 변화: {sum(shifts)/len(shifts):.2f}  "
                  f"max: {max(shifts)}  new entries: {len(set(id_rank1)-set(id_rank0))}")


if __name__ == "__main__":
    main()
