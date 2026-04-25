"""scripts/e2e_eval.py — 3채널 통합 E2E 품질 평가.

Dense-only / Dense+Sparse / Dense+Sparse+ASF 세 구성을 같은 쿼리 집합에
대해 실행하고 top-K 결과의 키워드 히트율(fn 메트릭) 과
caption-aware precision (ct 메트릭) 을 비교.

레이블이 없는 실사용 코퍼스 평가이므로 절대 점수보다 구성 간 **상대 개선**
이 주요 지표. 결과는 콘솔 표 + JSON 저장.

공통 라이브러리: scripts/_bench_common.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(ROOT / "App" / "backend")

import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from services.trichef.unified_engine import TriChefEngine  # noqa: E402
from _bench_common import ContentGoldDB  # noqa: E402


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

    print("[e2e_eval] content-aware gold DB 구축 중...")
    gold_db = ContentGoldDB()

    report: dict = {"per_query": [], "summary": {}}
    totals = {name: {"fn_hits": 0, "fn_returned": 0,
                     "ct_hits": 0, "ct_returned": 0, "ct_gold_queries": 0}
              for name, _ in CONFIGS}

    for q, dom, kws in EVAL_SET:
        # content gold — 쿼리당 1회 계산
        gold_set = gold_db.gold_ids(q, dom)
        gold_size = len(gold_set) if gold_set is not None else None

        row = {"query": q, "domain": dom, "kws": kws,
               "gold_size": gold_size, "configs": {}}
        print(f"\n=== {dom} | {q!r}  [gold={gold_size if gold_size is not None else 'N/A'}] ===")

        for name, cfg in CONFIGS:
            res = eng.search(q, dom, topk=TOPK, **cfg)

            # (A) filename-kw metric (backward-compat)
            fn_hits = sum(1 for r in res if _hit(r.id, kws))

            # (B) content-aware metric
            ct_hits_val: Optional[int] = None
            ct_p5: Optional[float] = None
            if gold_set is not None and gold_size:
                ct_hits_val = sum(1 for r in res if r.id in gold_set)
                ct_p5 = round(ct_hits_val / max(len(res), 1), 4)

            totals[name]["fn_hits"]    += fn_hits
            totals[name]["fn_returned"] += len(res)
            if ct_p5 is not None and ct_hits_val is not None:
                totals[name]["ct_hits"]    += ct_hits_val
                totals[name]["ct_returned"] += len(res)
                totals[name]["ct_gold_queries"] += 1

            row["configs"][name] = {
                "returned": len(res),
                "fn_hits":  fn_hits,
                "fn_p5":    round(fn_hits / max(len(res), 1), 4),
                "ct_hits":  ct_hits_val,
                "ct_p5":    ct_p5,
                "gold_size": gold_size,
                "top": [{"id": r.id, "score": r.score,
                         "asf": r.metadata.get("asf", 0),
                         "lex": r.metadata.get("lexical", 0)} for r in res],
            }
            ct_str = f"{ct_p5:.4f}" if ct_p5 is not None else "N/A "
            print(f"  [{name:14s}] returned={len(res)}/{TOPK}"
                  f"  fn_hits={fn_hits}  fn_p5={fn_hits/max(len(res),1):.3f}"
                  f"  ct_p5={ct_str}")
            for r in res[:3]:
                fn_tag = "F" if _hit(r.id, kws) else " "
                ct_tag = "C" if (gold_set and r.id in gold_set) else " "
                print(f"    [{fn_tag}{ct_tag}] s={r.score:.3f} asf={r.metadata.get('asf',0):.2f} "
                      f"lex={r.metadata.get('lexical',0):.2f}  {r.id}")
        report["per_query"].append(row)

    # ── summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"{'config':<16} {'fn_rate':<10} {'ct_p5':<10} {'avg_returned':<14}")
    print("-" * 70)
    n_q = len(EVAL_SET)
    for name, _ in CONFIGS:
        t = totals[name]
        fn_rate = t["fn_hits"] / max(t["fn_returned"], 1)
        ct_rate = (t["ct_hits"] / max(t["ct_returned"], 1)
                   if t["ct_returned"] else None)
        avg_ret = t["fn_returned"] / n_q
        ct_str = f"{ct_rate:.3f}" if ct_rate is not None else "N/A"
        report["summary"][name] = {
            "fn_rate":    round(fn_rate, 4),
            "fn_hits":    t["fn_hits"],
            "fn_returned": t["fn_returned"],
            "ct_p5":      round(ct_rate, 4) if ct_rate is not None else None,
            "ct_hits":    t["ct_hits"],
            "ct_returned": t["ct_returned"],
            "ct_gold_queries": t["ct_gold_queries"],
            "avg_returned": round(avg_ret, 2),
        }
        print(f"{name:<16} {fn_rate:<10.3f} {ct_str:<10} {avg_ret:<14.2f}")

    out = ROOT / "DI_TriCHEF" / "results" / "e2e_eval_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    main()
