"""[검증] v24 캡션 매칭 보너스 — /api/search 전체 파이프라인 (reranker 포함)."""
from __future__ import annotations
import os, sys
from pathlib import Path
from urllib.parse import quote

os.environ["TRICHEF_USE_RERANKER"] = "1"  # 라이브 앱과 동일하게 reranker 활성

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "App" / "backend"))

from app import app  # noqa: E402

client = app.test_client()

for q in ["햄버거", "운동하는 사람", "커피", "강아지", "피자"]:
    resp = client.get(f"/api/search?q={quote(q)}&top_k=12&type=image")
    data = resp.get_json() or {}
    rs = data.get("results") or data.get("top") or data.get("items") or []
    print(f"\n=== '{q}'  ({len(rs)}건, keys={list(data.keys())}) ===")
    for i, r in enumerate(rs, 1):
        cap = (r.get("snippet") or "").replace("\n", " ")
        conf = r.get("confidence") or 0
        dense = r.get("dense") or 0
        rr = r.get("rerank_score")
        rr_s = f"{rr:.2f}" if rr is not None else "None"
        print(f"  {i:2d} conf={conf:.3f} dense={dense:.3f} rr={rr_s:>7s}  "
              f"{(r.get('file_name') or '')[:28]:28s} | {cap[:62]}")
