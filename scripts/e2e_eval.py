"""scripts/e2e_eval.py — 3채널 통합 E2E 품질 평가.

Dense-only / Dense+Sparse / Dense+Sparse+ASF 세 구성을 같은 쿼리 집합에
대해 실행하고 top-K 결과의 키워드 히트율(proxy precision)을 비교.

레이블이 없는 실사용 코퍼스 평가이므로 절대 점수보다 구성 간 **상대 개선**
이 주요 지표. 결과는 콘솔 표 + JSON 저장.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from services.trichef.unified_engine import TriChefEngine  # noqa: E402


# (쿼리, 도메인, 결과 id/경로에서 기대되는 키워드 일부)
EVAL_SET: list[tuple[str, str, list[str]]] = [
    ("환경 정책", "doc_page", ["환경", "정책", "기후", "탄소", "그린"]),
    ("인공지능 교육", "doc_page", ["인공지능", "AI", "교육", "SW", "소프트웨어"]),
    ("탄소중립", "doc_page", ["탄소", "중립", "기후", "환경", "ESG"]),
    ("디지털 전환", "doc_page", ["디지털", "전환", "DX", "SW", "ICT"]),
    ("반도체 산업", "doc_page", ["반도체", "산업", "Samsung", "하이닉스"]),
    ("사람 얼굴", "image", ["face", "portrait", "person"]),
]

TOPK = 5
CONFIGS = [
    ("dense",         {"use_lexical": False, "use_asf": False}),
    ("dense+sparse",  {"use_lexical": True,  "use_asf": False}),
    ("dense+sp+asf",  {"use_lexical": True,  "use_asf": True}),
]


def _hit(id_str: str, kws: list[str]) -> bool:
    low = id_str.lower()
    return any(k.lower() in low for k in kws)


def main():
    eng = TriChefEngine()
    report: dict = {"per_query": [], "summary": {}}

    totals = {name: {"hits": 0, "returned": 0} for name, _ in CONFIGS}

    for q, dom, kws in EVAL_SET:
        row = {"query": q, "domain": dom, "kws": kws, "configs": {}}
        print(f"\n=== {dom} | {q!r} ===")
        for name, cfg in CONFIGS:
            res = eng.search(q, dom, topk=TOPK, **cfg)
            hits = sum(1 for r in res if _hit(r.id, kws))
            totals[name]["hits"] += hits
            totals[name]["returned"] += len(res)
            row["configs"][name] = {
                "returned": len(res),
                "hits": hits,
                "top": [{"id": r.id, "score": r.score,
                         "asf": r.metadata.get("asf", 0),
                         "lex": r.metadata.get("lexical", 0)} for r in res],
            }
            print(f"  [{name:14s}] returned={len(res)}/{TOPK}  kw_hits={hits}")
            for r in res[:3]:
                tag = "*" if _hit(r.id, kws) else " "
                print(f"    {tag} s={r.score:.3f} asf={r.metadata.get('asf',0):.2f} "
                      f"lex={r.metadata.get('lexical',0):.2f}  {r.id}")
        report["per_query"].append(row)

    print("\n" + "=" * 60)
    print(f"{'config':<16} {'hit_rate':<12} {'avg_returned':<14}")
    print("-" * 60)
    n_q = len(EVAL_SET)
    for name, _ in CONFIGS:
        t = totals[name]
        hit_rate = t["hits"] / max(t["returned"], 1)
        avg_ret = t["returned"] / n_q
        report["summary"][name] = {
            "hit_rate": hit_rate, "avg_returned": avg_ret,
            "total_hits": t["hits"], "total_returned": t["returned"],
        }
        print(f"{name:<16} {hit_rate:<12.3f} {avg_ret:<14.2f}")

    out = ROOT / "Docs" / "e2e_eval_report.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    main()
