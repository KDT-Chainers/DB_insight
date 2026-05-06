"""5도메인 검색 검증 스크립트 — Phase 1.

70 케이스를 KO/EN 양방향으로 실행하고 4가지 지표 기반으로 PASS/WARN/FAIL 판정.

사용:
    python scripts/validate_5domain.py
    python scripts/validate_5domain.py --top-k 30
    python scripts/validate_5domain.py --tag phase1   (보고서 파일명에 태그 부여)

산출물:
    md/_validation_<tag>.md       사람이 읽는 보고서
    md/_validation_<tag>.csv      회귀 비교용 raw 데이터
"""
from __future__ import annotations
import sys, os, io, json, time, argparse, urllib.request, urllib.parse
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 프로젝트 root 기준 경로
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from validation_cases import CASES, Case  # noqa: E402

PROJECT_ROOT = HERE.parents[3]              # repo root (DB_insight)
MD_DIR = PROJECT_ROOT / "md"
MD_DIR.mkdir(exist_ok=True)

API = "http://127.0.0.1:5001/api/search"


# ─── 검색 호출 ────────────────────────────────────────────────────────────
def search(query: str, domain: str, top_k: int) -> list[dict]:
    """domain → backend type 매핑 후 호출."""
    type_map = {"doc": "doc", "image": "image", "video": "video",
                "audio": "audio", "bgm": "bgm"}
    tp = type_map[domain]
    url = f"{API}?q={urllib.parse.quote(query)}&top_k={top_k}&type={tp}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
        return data.get("results", []) or []
    except Exception as e:
        print(f"  ⚠ HTTP error '{query}' [{domain}]: {e}", file=sys.stderr)
        return []


# ─── 평가 ─────────────────────────────────────────────────────────────────
def keyword_in_top_k(results: list[dict], keyword: str, k: int = 5) -> bool:
    """top-k 결과의 file_name / file_path / snippet 에 keyword 포함 여부."""
    if not keyword:
        return True
    needle = keyword.lower()
    for r in results[:k]:
        hay = " ".join([
            r.get("file_name", ""),
            r.get("file_path", ""),
            r.get("snippet",   ""),
        ]).lower()
        if needle in hay:
            return True
    return False


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def file_ids(results: list[dict]) -> list[str]:
    return [r.get("file_name") or r.get("file_path") or "?" for r in results]


def evaluate(case: Case, ko: list[dict], en: list[dict]) -> dict:
    top1_ko = ko[0] if ko else None
    top1_en = en[0] if en else None

    top1_conf = float(top1_ko.get("confidence", 0.0)) if top1_ko else 0.0
    top1_sim  = float(top1_ko.get("similarity", top1_ko.get("confidence", 0.0))
                      if top1_ko else 0.0)
    top1_dense = float(top1_ko.get("dense", 0.0)) if top1_ko else 0.0

    kw_ok_ko = keyword_in_top_k(ko, case.expected_keyword, k=5)
    kw_ok_en = keyword_in_top_k(en, case.expected_keyword, k=5)
    consistency = jaccard(file_ids(ko[:10]), file_ids(en[:10]))

    pass_count = 0
    if top1_conf >= case.min_top1_conf:                    pass_count += 1
    if top1_sim  >= case.min_top1_sim:                     pass_count += 1
    if (kw_ok_ko or case.expected_keyword is None):        pass_count += 1
    if consistency >= case.min_consistency:                pass_count += 1

    if pass_count == 4:
        verdict = "PASS"
    elif pass_count >= 2:
        verdict = "WARN"
    else:
        verdict = "FAIL"

    return {
        "id": case.id, "domain": case.domain, "category": case.category,
        "ko": case.ko_query, "en": case.en_query,
        "expected": case.expected_keyword or "",
        "ko_n": len(ko), "en_n": len(en),
        "top1_conf": round(top1_conf, 3),
        "top1_sim":  round(top1_sim,  3),
        "top1_dense": round(top1_dense, 3),
        "top1_file": (top1_ko.get("file_name", "") if top1_ko else "")[:60],
        "kw_ok_ko": kw_ok_ko, "kw_ok_en": kw_ok_en,
        "consistency": round(consistency, 2),
        "pass_count": pass_count, "verdict": verdict,
    }


# ─── 보고서 생성 ──────────────────────────────────────────────────────────
ICONS = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}


def write_csv(rows: list[dict], path: Path) -> None:
    import csv
    cols = ["id", "domain", "category", "verdict", "pass_count",
            "top1_conf", "top1_sim", "top1_dense",
            "ko_n", "en_n", "kw_ok_ko", "kw_ok_en", "consistency",
            "ko", "en", "expected", "top1_file"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_md(rows: list[dict], path: Path, elapsed: float) -> None:
    lines: list[str] = []
    lines.append(f"# 5도메인 검색 검증 보고서\n")
    lines.append(f"_생성: {time.strftime('%Y-%m-%d %H:%M:%S')} · 실행 {elapsed:.1f}s_\n")

    # 요약
    lines.append("## 요약\n")
    lines.append("| 도메인 | 케이스 | ✅PASS | ⚠️WARN | ❌FAIL | 합격률 | 평균 신뢰도(top1) | 평균 유사도(top1) |")
    lines.append("|---|---|---|---|---|---|---|---|")

    by_dom: dict[str, list[dict]] = {}
    for r in rows:
        by_dom.setdefault(r["domain"], []).append(r)

    for dom, lst in by_dom.items():
        cnt = Counter(r["verdict"] for r in lst)
        avg_conf = sum(r["top1_conf"] for r in lst) / max(1, len(lst))
        avg_sim  = sum(r["top1_sim"]  for r in lst) / max(1, len(lst))
        rate = cnt["PASS"] / max(1, len(lst)) * 100
        lines.append(f"| {dom} | {len(lst)} | {cnt['PASS']} | {cnt['WARN']} | "
                     f"{cnt['FAIL']} | {rate:.0f}% | {avg_conf:.3f} | {avg_sim:.3f} |")

    total = Counter(r["verdict"] for r in rows)
    avg_conf_all = sum(r["top1_conf"] for r in rows) / max(1, len(rows))
    avg_sim_all  = sum(r["top1_sim"]  for r in rows) / max(1, len(rows))
    rate_all = total["PASS"] / max(1, len(rows)) * 100
    lines.append(f"| **합계** | **{len(rows)}** | **{total['PASS']}** | "
                 f"**{total['WARN']}** | **{total['FAIL']}** | "
                 f"**{rate_all:.0f}%** | **{avg_conf_all:.3f}** | **{avg_sim_all:.3f}** |")

    # 도메인별 상세
    for dom, lst in by_dom.items():
        lines.append(f"\n## {dom}\n")
        lines.append("| ID | Cat | KO 쿼리 | top1 신뢰 | top1 유사 | top1 dense | KW | KO/EN n | 일관성 | 판정 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in lst:
            kw = "✓" if r["kw_ok_ko"] else "✗"
            n_pair = f"{r['ko_n']}/{r['en_n']}"
            lines.append(f"| {r['id']} | {r['category']} | {r['ko']} | "
                         f"{r['top1_conf']:.2f} | {r['top1_sim']:.2f} | "
                         f"{r['top1_dense']:.2f} | {kw} | {n_pair} | "
                         f"{r['consistency']:.2f} | {ICONS[r['verdict']]} {r['verdict']} |")

    # 문제 케이스
    fail_rows = [r for r in rows if r["verdict"] == "FAIL"]
    warn_rows = [r for r in rows if r["verdict"] == "WARN"]
    if fail_rows or warn_rows:
        lines.append("\n## 주요 문제 케이스\n")
        for r in fail_rows + warn_rows:
            tag = ICONS[r["verdict"]]
            issues = []
            if r["top1_conf"] < 0.70: issues.append(f"신뢰도↓({r['top1_conf']:.2f})")
            if r["top1_sim"]  < 0.60: issues.append(f"유사도↓({r['top1_sim']:.2f})")
            if not r["kw_ok_ko"] and r["expected"]:
                issues.append(f"키워드 누락(KO)")
            if not r["kw_ok_en"] and r["expected"]:
                issues.append(f"키워드 누락(EN)")
            if r["consistency"] < 0.30: issues.append(f"일관성↓({r['consistency']:.2f})")
            if r["ko_n"] == 0: issues.append("KO 결과 0건")
            if r["en_n"] == 0: issues.append("EN 결과 0건")
            lines.append(f"- {tag} **[{r['domain']}/{r['category']}] {r['id']}** "
                         f"(`{r['ko']}` ↔ `{r['en']}`): {', '.join(issues) or '-'}")

    path.write_text("\n".join(lines), encoding="utf-8")


# ─── main ─────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=30)
    ap.add_argument("--tag",   type=str, default="phase1")
    args = ap.parse_args()

    print(f"[validate] {len(CASES)} 케이스, top_k={args.top_k}, tag={args.tag}")
    print(f"[validate] Backend: {API}\n")

    t0 = time.time()
    rows = []
    for i, case in enumerate(CASES, 1):
        ko = search(case.ko_query, case.domain, args.top_k)
        en = search(case.en_query, case.domain, args.top_k)
        r = evaluate(case, ko, en)
        rows.append(r)
        icon = ICONS[r["verdict"]]
        print(f"  [{i:2}/{len(CASES)}] {icon} {r['id']:32} "
              f"conf={r['top1_conf']:.2f} sim={r['top1_sim']:.2f} "
              f"n={r['ko_n']:2}/{r['en_n']:2} jc={r['consistency']:.2f}")

    elapsed = time.time() - t0
    md_path  = MD_DIR / f"_validation_{args.tag}.md"
    csv_path = MD_DIR / f"_validation_{args.tag}.csv"
    write_md(rows, md_path, elapsed)
    write_csv(rows, csv_path)

    total = Counter(r["verdict"] for r in rows)
    print(f"\n[summary] {total['PASS']}P / {total['WARN']}W / "
          f"{total['FAIL']}F / total {len(rows)}  ({elapsed:.1f}s)")
    print(f"[output]  {md_path}")
    print(f"[output]  {csv_path}")


if __name__ == "__main__":
    main()
