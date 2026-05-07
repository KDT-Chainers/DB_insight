"""MPLC Step 1 — 80케이스 × 5도메인 × top 100 features 수집.

각 결과에서 7개 features 추출:
  f1 = dense           (raw cosine)
  f2 = sparse          (BM25 / sparse_agg)
  f3 = asf             (token set match)
  f4 = rerank_score    (cross-encoder)
  f5 = keyword_count   (query token in fn+snippet)
  f6 = filename_substr (query substring in filename)
  f7 = z_dense         (도메인 내 정규화)

Relevant 라벨 (ground truth):
  - case.domain 일치 + case.expected_keyword 매칭 → 1
  - 그 외 → 0

산출:
  md/_mplc_features.csv     (raw datapoints)
  md/_mplc_separability.md  (분리 가능성 분석)
"""
from __future__ import annotations
import sys, json, csv, urllib.request, urllib.parse, statistics
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validation_cases import CASES  # noqa: E402

API = "http://127.0.0.1:5001/api/search"


def search(query: str, domain: str, top_k: int = 100) -> list[dict]:
    type_map = {"doc": "doc", "image": "image", "video": "video",
                "audio": "audio", "bgm": "bgm"}
    tp = type_map[domain]
    url = f"{API}?q={urllib.parse.quote(query)}&top_k={top_k}&type={tp}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return json.loads(resp.read()).get("results", []) or []
    except Exception:
        return []


def extract_features(r: dict, query: str) -> dict:
    """7 features 추출."""
    fn = (r.get("file_name") or "").lower()
    snippet = (r.get("snippet") or "").lower()
    fp = (r.get("file_path") or "").lower()
    q_lower = query.lower().strip()
    q_tokens = [t for t in query.split() if len(t) >= 2]

    # f5: keyword count — query token 중 fn/snippet에 포함된 비율
    if q_tokens:
        hits = sum(1 for t in q_tokens if t.lower() in (fn + " " + snippet + " " + fp))
        f5 = hits / len(q_tokens)
    else:
        f5 = 0.0

    # f6: filename substring (query 전체 substring)
    f6 = 1.0 if q_lower and q_lower in (fn + " " + fp) else 0.0

    return {
        "dense": float(r.get("dense", 0) or 0),
        "sparse": float(r.get("lexical", 0) or r.get("sparse", 0) or 0),
        "asf": float(r.get("asf", 0) or 0),
        "rerank": float(r.get("rerank_score", 0) or 0),
        "keyword_count": float(f5),
        "filename_substr": float(f6),
        "z_dense": float(r.get("z_score", 0) or 0),
    }


def is_relevant(case_domain: str, case_kw: str | None,
                result: dict, current_domain: str) -> int:
    """Ground truth: case 의 도메인 일치 + expected_keyword 매칭."""
    if case_domain != current_domain:
        return 0
    if not case_kw:
        return 0  # ground truth 없는 케이스 → 학습 데이터 제외 (0)
    needle = case_kw.lower()
    hay = " ".join([result.get("file_name", ""), result.get("file_path", ""),
                    result.get("snippet", "")]).lower()
    return 1 if needle in hay else 0


def main() -> None:
    sys.stdout = sys.stdout.reconfigure(encoding="utf-8") or sys.stdout
    project_root = Path(__file__).resolve().parents[3]
    out_csv = project_root / "md" / "_mplc_features.csv"
    out_md = project_root / "md" / "_mplc_separability.md"
    out_csv.parent.mkdir(exist_ok=True)

    # [v17] expand_bilingual: 서빙과 동일한 bilingual 확장 쿼리로 피처 추출
    # EN 쿼리 "artificial intelligence" → "artificial intelligence 인공지능" 로 확장
    # → keyword_count 이 한국어 콘텐츠에서도 발화 → 학습/서빙 피처 일관성 확보
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from services.query_expand import expand_bilingual as _expand_bilingual
    except Exception:
        _expand_bilingual = lambda q: q  # type: ignore

    print(f"[mplc-collect] {len(CASES)} 케이스 × 5도메인 × top 100 수집 (KO+EN)...")
    rows: list[dict] = []
    for i, case in enumerate(CASES):
        # 한국어+영어 쿼리 모두 수집 → MPLC cross-lingual 학습
        queries_to_run = [(case.ko_query, "ko")]
        if getattr(case, "en_query", None):
            queries_to_run.append((case.en_query, "en"))
        for dom in ("doc", "image", "video", "audio", "bgm"):
            for query, lang in queries_to_run:
                results = search(query, dom, top_k=100)
                # [v17] 학습/서빙 피처 일관성:
                # 서빙 시 MPLC는 expand_bilingual(query)로 keyword_count 계산
                # (EN 쿼리 + 한국어 번역 토큰이 한국어 콘텐츠에서 keyword_count 발화)
                # → 학습도 동일하게 expanded_query로 피처 추출해야 일관성 보장
                expanded_q = _expand_bilingual(query)
                for r in results:
                    feats = extract_features(r, expanded_q)  # 서빙과 동일한 expanded query 사용
                    rel = is_relevant(case.domain, case.expected_keyword, r, dom)
                    rows.append({
                        "case_id": f"{case.id}__{lang}", "case_domain": case.domain,
                        "result_domain": dom, "query": query,
                        "expected_kw": case.expected_keyword or "",
                        "file_name": (r.get("file_name") or "")[:80],
                        "relevant": rel, **feats,
                    })
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(CASES)}")

    # CSV 저장
    if rows:
        cols = list(rows[0].keys())
        with out_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    print(f"[output] {out_csv}  ({len(rows)} rows)")

    # 분리 가능성 분석 (도메인별, feature별)
    by_dom: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_dom[r["result_domain"]].append(r)

    feats = ["dense", "sparse", "asf", "rerank",
             "keyword_count", "filename_substr", "z_dense"]

    md_lines = ["# MPLC Step 1 — Multi-feature Separability\n",
                f"_총 {len(rows)} datapoints / 80 케이스_\n",
                "## 도메인별 Feature 분리 가능성\n",
                "각 도메인의 relevant vs irrelevant 분포 차이 (mean gap, p5 gap)."]

    for dom in ("doc", "image", "video", "audio", "bgm"):
        lst = by_dom[dom]
        rel = [r for r in lst if r["relevant"] == 1]
        irr = [r for r in lst if r["relevant"] == 0]
        if not rel:
            md_lines.append(f"\n### {dom} — relevant 0건 (skip)")
            continue
        md_lines.append(f"\n### {dom}  (rel={len(rel)}, irr={len(irr)})")
        md_lines.append("| feature | rel 평균 | irr 평균 | mean gap | rel_p5 | irr_p95 | p5-p95 gap |")
        md_lines.append("|---|---|---|---|---|---|---|")
        for f in feats:
            rel_v = sorted(r[f] for r in rel)
            irr_v = sorted(r[f] for r in irr)
            if not rel_v:
                continue
            rel_mean = statistics.mean(rel_v)
            irr_mean = statistics.mean(irr_v) if irr_v else 0.0
            rel_p5 = rel_v[max(0, len(rel_v)//20)]
            irr_p95 = irr_v[min(len(irr_v)-1, int(len(irr_v)*0.95))] if irr_v else 0.0
            md_lines.append(
                f"| {f} | {rel_mean:.3f} | {irr_mean:.3f} | "
                f"{rel_mean - irr_mean:+.3f} | {rel_p5:.3f} | {irr_p95:.3f} | "
                f"{rel_p5 - irr_p95:+.3f} |"
            )

    out_md.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[output] {out_md}")

    # 콘솔에 핵심 요약
    print("\n=== 도메인별 Single-Feature p5-p95 gap (양수면 분리 가능) ===")
    print(f"{'도메인':6} {'feature':18} {'rel_p5':>7} {'irr_p95':>8} {'gap':>7}")
    for dom in ("doc", "image", "video", "audio", "bgm"):
        lst = by_dom[dom]
        rel = [r for r in lst if r["relevant"] == 1]
        irr = [r for r in lst if r["relevant"] == 0]
        if not rel: continue
        for f in feats:
            rel_v = sorted(r[f] for r in rel)
            irr_v = sorted(r[f] for r in irr)
            if not rel_v: continue
            rel_p5 = rel_v[max(0, len(rel_v)//20)]
            irr_p95 = irr_v[min(len(irr_v)-1, int(len(irr_v)*0.95))] if irr_v else 0.0
            gap = rel_p5 - irr_p95
            marker = " ✓" if gap > 0 else ""
            print(f"{dom:6} {f:18} {rel_p5:>7.3f} {irr_p95:>8.3f} {gap:>+7.3f}{marker}")


if __name__ == "__main__":
    main()
