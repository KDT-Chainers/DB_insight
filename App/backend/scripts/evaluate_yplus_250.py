"""Y+ 종합 성능 평가 — 250 검색 입력 (5도메인 × 50, 4가지 form).

평가 기준:
  1. 검색 결과 수 (top_k=30)
  2. top1 confidence / similarity / mplc
  3. 도메인 정합성: case.domain == top1.file_type ?
  4. 도메인 정합성 top5: case.domain in top5.file_type ?
  5. form 별 합격률 (word vs phrase vs sentence vs stt)

산출:
  md/_yplus_250_eval.md / .csv
"""
from __future__ import annotations
import sys, json, csv, urllib.request, urllib.parse, time
from pathlib import Path
from collections import defaultdict, Counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validation_cases_250 import CASES_250  # noqa: E402

API = "http://127.0.0.1:5001/api/search"
TOP_K = 30


def search(query: str, top_k: int = 30) -> list[dict]:
    url = f"{API}?q={urllib.parse.quote(query)}&top_k={top_k}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return json.loads(resp.read()).get("results", []) or []
    except Exception:
        return []


def evaluate(case, results: list[dict]) -> dict:
    top1 = results[0] if results else None
    top5 = results[:5]

    top1_conf = float(top1.get("confidence", 0)) if top1 else 0.0
    top1_sim  = float(top1.get("similarity", top1.get("dense", 0)) if top1 else 0)
    top1_mplc = float(top1.get("mplc_score", top1_conf) if top1 else 0)
    top1_dom  = top1.get("file_type", "") if top1 else ""

    # 도메인 정합성
    case_dom_ft = {"doc": "doc", "image": "image", "video": "video",
                   "audio": "audio", "bgm": "bgm"}
    expected_ft = case_dom_ft.get(case.domain, "")
    top1_match = (top1_dom == expected_ft)
    top5_match = any(r.get("file_type") == expected_ft for r in top5)

    return {
        "id": case.id, "domain": case.domain, "form": case.form,
        "query": case.query, "n": len(results),
        "top1_dom": top1_dom, "top1_conf": round(top1_conf, 3),
        "top1_sim": round(top1_sim, 3), "top1_mplc": round(top1_mplc, 3),
        "top1_file": (top1.get("file_name", "") if top1 else "")[:60],
        "top1_match": top1_match, "top5_match": top5_match,
    }


def main() -> None:
    sys.stdout = sys.stdout.reconfigure(encoding="utf-8") or sys.stdout
    project_root = Path(__file__).resolve().parents[3]
    out_md = project_root / "md" / "_yplus_250_eval.md"
    out_csv = project_root / "md" / "_yplus_250_eval.csv"
    out_md.parent.mkdir(exist_ok=True)

    print(f"[eval] {len(CASES_250)} 케이스 평가 시작...")
    rows = []
    t0 = time.time()
    for i, case in enumerate(CASES_250):
        results = search(case.query, top_k=TOP_K)
        row = evaluate(case, results)
        rows.append(row)
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(CASES_250)} ({time.time()-t0:.1f}s)")
    elapsed = time.time() - t0
    print(f"[eval] 완료 {elapsed:.1f}s")

    # CSV
    cols = list(rows[0].keys())
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    # 분석
    total_top1_match = sum(1 for r in rows if r["top1_match"])
    total_top5_match = sum(1 for r in rows if r["top5_match"])
    total_n = len(rows)

    by_dom_form = defaultdict(lambda: {"top1": 0, "top5": 0, "n": 0,
                                        "conf_sum": 0.0, "mplc_sum": 0.0})
    for r in rows:
        k = (r["domain"], r["form"])
        by_dom_form[k]["n"] += 1
        by_dom_form[k]["top1"] += int(r["top1_match"])
        by_dom_form[k]["top5"] += int(r["top5_match"])
        by_dom_form[k]["conf_sum"] += r["top1_conf"]
        by_dom_form[k]["mplc_sum"] += r["top1_mplc"]

    print(f"\n=== 종합 결과 ===")
    print(f"총 케이스: {total_n}")
    print(f"top1 도메인 정합: {total_top1_match}/{total_n} = "
          f"{total_top1_match*100//total_n}%")
    print(f"top5 도메인 정합: {total_top5_match}/{total_n} = "
          f"{total_top5_match*100//total_n}%")
    print(f"실행 시간: {elapsed:.1f}s")

    # Form 별
    print(f"\n=== form 별 정합률 ===")
    form_stats = defaultdict(lambda: {"top1": 0, "top5": 0, "n": 0})
    for r in rows:
        form_stats[r["form"]]["n"] += 1
        form_stats[r["form"]]["top1"] += int(r["top1_match"])
        form_stats[r["form"]]["top5"] += int(r["top5_match"])
    for form, s in form_stats.items():
        print(f"  {form:9} top1={s['top1']}/{s['n']} ({s['top1']*100//s['n']}%) "
              f"top5={s['top5']}/{s['n']} ({s['top5']*100//s['n']}%)")

    # 도메인 × form
    print(f"\n=== 도메인 × form 매트릭스 ===")
    print(f"{'domain':6} {'form':9} {'n':>3} {'top1%':>6} {'top5%':>6} "
          f"{'avg_conf':>8} {'avg_mplc':>8}")
    for (dom, form), s in sorted(by_dom_form.items()):
        n = s["n"]
        print(f"{dom:6} {form:9} {n:>3} "
              f"{s['top1']*100//n:>6}% {s['top5']*100//n:>6}% "
              f"{s['conf_sum']/n:>8.3f} {s['mplc_sum']/n:>8.3f}")

    # MD 보고서
    md = ["# Y+ 종합 성능 평가 (250 검색 입력)\n",
          f"_생성: {time.strftime('%Y-%m-%d %H:%M:%S')} · 실행 {elapsed:.1f}s_\n",
          "## 종합\n",
          f"- 총 케이스: **{total_n}**",
          f"- top1 도메인 정합: **{total_top1_match}/{total_n} ({total_top1_match*100//total_n}%)**",
          f"- top5 도메인 정합: **{total_top5_match}/{total_n} ({total_top5_match*100//total_n}%)**",
          "\n## Form 별 정합률\n",
          "| form | n | top1 정합 | top5 정합 |",
          "|---|---|---|---|"]
    for form, s in form_stats.items():
        md.append(f"| {form} | {s['n']} | {s['top1']*100//s['n']}% | {s['top5']*100//s['n']}% |")

    md.append("\n## 도메인 × form 매트릭스\n")
    md.append("| domain | form | n | top1 정합 | top5 정합 | avg conf | avg mplc |")
    md.append("|---|---|---|---|---|---|---|")
    for (dom, form), s in sorted(by_dom_form.items()):
        n = s["n"]
        md.append(f"| {dom} | {form} | {n} | "
                  f"{s['top1']*100//n}% | {s['top5']*100//n}% | "
                  f"{s['conf_sum']/n:.3f} | {s['mplc_sum']/n:.3f} |")

    # 실패 케이스 (top5 도메인 불일치)
    fails = [r for r in rows if not r["top5_match"]]
    if fails:
        md.append(f"\n## top5 도메인 불일치 {len(fails)}건\n")
        md.append("| id | domain | form | query | top1_dom | top1_file |")
        md.append("|---|---|---|---|---|---|")
        for r in fails:
            md.append(f"| {r['id']} | {r['domain']} | {r['form']} | "
                      f"{r['query'][:40]} | {r['top1_dom']} | {r['top1_file']} |")

    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"\n[output] {out_md}")
    print(f"[output] {out_csv}")


if __name__ == "__main__":
    main()
