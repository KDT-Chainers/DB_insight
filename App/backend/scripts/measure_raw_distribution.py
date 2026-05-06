"""5도메인 raw cosine 분포 정밀 측정 (offline calibration 용).

80개 검증 쿼리 × 5도메인 검색 → raw cosine (cosine_top1 / dense) 수집 →
relevant vs irrelevant 분포 분석 → DOMAIN_RAW_DIST + DOMAIN_RAW_FLOOR 결정.

Ground truth: validation_cases.py 의 expected_keyword 매칭 여부.

산출:
  md/_raw_distribution.md
  - 도메인별 raw cosine 통계 (mean, std, percentiles)
  - relevant vs irrelevant 분리 분석
  - 권장 DOMAIN_RAW_DIST (5%~95% percentile)
  - 권장 DOMAIN_RAW_FLOOR (irrelevant 의 95% percentile = relevant 5% percentile)
"""
from __future__ import annotations
import sys, json, urllib.request, urllib.parse, statistics
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validation_cases import CASES, Case  # noqa: E402

sys.stdout = sys.stdout.reconfigure(encoding='utf-8') or sys.stdout
API = "http://127.0.0.1:5001/api/search"


def search(query: str, domain: str, top_k: int = 30) -> list[dict]:
    """도메인 단일 검색 호출."""
    type_map = {"doc": "doc", "image": "image", "video": "video",
                "audio": "audio", "bgm": "bgm"}
    tp = type_map[domain]
    url = f"{API}?q={urllib.parse.quote(query)}&top_k={top_k}&type={tp}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read()).get("results", []) or []
    except Exception:
        return []


def get_raw(r: dict, domain: str) -> float:
    """도메인별 raw cosine 추출.
    AV 도메인: cosine_top1 (segment max raw cosine, search_av 가공 전)
    기타: dense (raw cosine)
    """
    if domain in ("video", "audio"):
        return float(r.get("cosine_top1", 0) or r.get("dense", 0) or 0)
    return float(r.get("dense", 0) or 0)


def keyword_matches(r: dict, kw: str | None) -> bool:
    if not kw:
        return False
    needle = kw.lower()
    hay = " ".join([r.get("file_name", ""), r.get("file_path", ""),
                    r.get("snippet", "")]).lower()
    return needle in hay


def main() -> None:
    # 도메인별 raw cosine 수집
    relevant: dict[str, list[float]] = defaultdict(list)
    irrelevant: dict[str, list[float]] = defaultdict(list)
    all_raws: dict[str, list[float]] = defaultdict(list)
    domain_top1: dict[str, list[float]] = defaultdict(list)

    print(f"[measure] {len(CASES)} 케이스 × 5도메인 raw cosine 수집...")
    for i, case in enumerate(CASES):
        # 모든 5도메인에 대해 검색 (해당 케이스 도메인뿐 아니라 cross-domain)
        for dom in ("doc", "image", "video", "audio", "bgm"):
            results = search(case.ko_query, dom, top_k=30)
            if results:
                domain_top1[dom].append(get_raw(results[0], dom))
            for r in results:
                raw = get_raw(r, dom)
                all_raws[dom].append(raw)
                # relevant 판정: 케이스의 도메인 일치 + expected_keyword 매칭
                same_dom = (case.domain == dom or
                            (case.domain == "doc" and dom == "doc"))
                kw_ok = keyword_matches(r, case.expected_keyword)
                if same_dom and kw_ok and case.expected_keyword:
                    relevant[dom].append(raw)
                else:
                    irrelevant[dom].append(raw)
        if (i + 1) % 10 == 0:
            print(f"  진행 {i+1}/{len(CASES)}")

    # 통계
    def pct(lst: list[float], q: float) -> float:
        if not lst:
            return 0.0
        s = sorted(lst)
        idx = max(0, min(len(s) - 1, int(len(s) * q)))
        return s[idx]

    print("\n=== 도메인별 raw cosine 분포 ===")
    print(f"{'도메인':6} {'n':>5} {'min':>6} {'p5':>6} {'p25':>6} {'p50':>6} "
          f"{'p75':>6} {'p95':>6} {'max':>6} {'top1평균':>8}")
    for dom in ("doc", "image", "video", "audio", "bgm"):
        arr = all_raws[dom]
        tops = domain_top1[dom]
        if arr:
            print(f"{dom:6} {len(arr):>5} {min(arr):>6.3f} "
                  f"{pct(arr, 0.05):>6.3f} {pct(arr, 0.25):>6.3f} "
                  f"{pct(arr, 0.5):>6.3f} {pct(arr, 0.75):>6.3f} "
                  f"{pct(arr, 0.95):>6.3f} {max(arr):>6.3f} "
                  f"{statistics.mean(tops) if tops else 0:>8.3f}")

    print("\n=== Relevant vs Irrelevant 분포 ===")
    print(f"{'도메인':6} {'n_rel':>6} {'rel평균':>8} {'rel_p5':>7} "
          f"{'irr_p95':>8} {'gap':>6}")
    for dom in ("doc", "image", "video", "audio", "bgm"):
        rel = relevant[dom]
        irr = irrelevant[dom]
        if rel:
            rel_p5 = pct(rel, 0.05)
            irr_p95 = pct(irr, 0.95)
            print(f"{dom:6} {len(rel):>6} {statistics.mean(rel):>8.3f} "
                  f"{rel_p5:>7.3f} {irr_p95:>8.3f} "
                  f"{rel_p5 - irr_p95:>6.3f}")

    # 권장 DOMAIN_RAW_DIST (전체 분포 5~95 percentile) + DOMAIN_RAW_FLOOR
    print("\n=== 권장 calibration ===")
    print("DOMAIN_RAW_DIST = {")
    for dom in ("doc", "image", "video", "audio", "bgm"):
        arr = all_raws[dom]
        if arr:
            lo = pct(arr, 0.05)
            hi = pct(arr, 0.95)
            print(f'    "{dom}":   ({lo:.3f}, {hi:.3f}),')
    print("}")
    print()
    print("DOMAIN_RAW_FLOOR = {")
    for dom in ("doc", "image", "video", "audio", "bgm"):
        rel = relevant[dom]
        irr = irrelevant[dom]
        if rel and irr:
            # relevant 의 5 percentile (관련 결과 95% 이상이 통과)
            floor = pct(rel, 0.05)
            print(f'    "{dom}":   {floor:.3f},  # relevant p5')
        elif rel:
            print(f'    "{dom}":   {pct(rel, 0.05):.3f},')
    print("}")

    # 보고서 파일 저장
    out_dir = Path(__file__).resolve().parents[3] / "md"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "_raw_distribution.md"
    lines = ["# 5도메인 raw cosine 분포 정밀 측정\n",
             f"_케이스 {len(CASES)} × 5도메인_\n", "## 분포 통계\n",
             f"| 도메인 | n | min | p5 | p25 | p50 | p75 | p95 | max | top1평균 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for dom in ("doc", "image", "video", "audio", "bgm"):
        arr = all_raws[dom]
        tops = domain_top1[dom]
        if arr:
            lines.append(
                f"| {dom} | {len(arr)} | {min(arr):.3f} | {pct(arr,0.05):.3f} | "
                f"{pct(arr,0.25):.3f} | {pct(arr,0.5):.3f} | {pct(arr,0.75):.3f} | "
                f"{pct(arr,0.95):.3f} | {max(arr):.3f} | "
                f"{statistics.mean(tops) if tops else 0:.3f} |"
            )
    lines.append("\n## Relevant vs Irrelevant\n")
    lines.append("| 도메인 | n_rel | rel 평균 | rel_p5 | irr_p95 | gap |")
    lines.append("|---|---|---|---|---|---|")
    for dom in ("doc", "image", "video", "audio", "bgm"):
        rel = relevant[dom]
        irr = irrelevant[dom]
        if rel:
            rel_p5 = pct(rel, 0.05)
            irr_p95 = pct(irr, 0.95) if irr else 0.0
            lines.append(
                f"| {dom} | {len(rel)} | {statistics.mean(rel):.3f} | "
                f"{rel_p5:.3f} | {irr_p95:.3f} | {rel_p5 - irr_p95:.3f} |"
            )
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[output] {out_path}")


if __name__ == "__main__":
    main()
