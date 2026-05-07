"""DI_TriCHEF/reranker/rerank_cli.py

실행:
    python DI_TriCHEF/reranker/rerank_cli.py --query "웃고 있는 강아지" --domain image --top-k 20
    python DI_TriCHEF/reranker/rerank_cli.py --query "지역사회 복지정책" --domain doc_page

기존 /api/admin/inspect 를 호출 → top-K 에 대해 cross-encoder rerank → 비교표 출력.
App/backend 무수정.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from DI_TriCHEF.reranker.post_rerank import rerank_rows  # noqa: E402

BACKEND = "http://127.0.0.1:5001"


def _inspect(query: str, domain: str, top_n: int) -> dict:
    r = requests.post(f"{BACKEND}/api/admin/inspect", json={
        "query": query, "domain": domain, "top_n": top_n,
        "use_lexical": True, "use_asf": True,
    }, timeout=300)
    r.raise_for_status()
    return r.json()


def _doc_text(doc_id: str, query: str, domain: str) -> str:
    r = requests.get(f"{BACKEND}/api/admin/doc-text",
                     params={"id": doc_id, "query": query, "domain": domain},
                     timeout=60)
    r.raise_for_status()
    return r.json().get("text", "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--domain", default="image", choices=["image", "doc_page"])
    ap.add_argument("--top-n", type=int, default=50)
    ap.add_argument("--top-k", type=int, default=20, help="rerank 대상 상위 K")
    args = ap.parse_args()

    print(f"[rerank-cli] inspect({args.domain}, top_n={args.top_n}) …")
    data = _inspect(args.query, args.domain, args.top_n)
    rows = data.get("rows", [])
    print(f"[rerank-cli] fetched {len(rows)} rows")

    def _provider(row):
        return _doc_text(row["id"], args.query, args.domain)

    print(f"[rerank-cli] reranking top-{args.top_k} …")
    reranked = rerank_rows(args.query, rows, _provider, top_k=args.top_k)

    print(f"\n{'rank':>4} {'new':>4} {'fused':>7} {'rerank':>7} {'final':>7}  filename")
    print("-" * 80)
    for r in reranked[:args.top_k]:
        print(f"{r.get('rank'):>4} "
              f"{r.get('reranked_rank', '-'):>4} "
              f"{r.get('fused', 0):>7.3f} "
              f"{r.get('rerank_norm', 0):>7.3f} "
              f"{r.get('final_score', 0):>7.3f}  "
              f"{r.get('filename', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
