"""scripts/generate_inspection_report.py — bench_results/ JSON → Markdown 리포트.

야간 점검 스크립트들이 생성한 JSON 결과를 취합하여 단일 Markdown 리포트를 작성.
가장 최신 타임스탬프 파일들을 자동 선택.

실행:
  python scripts/generate_inspection_report.py
  python scripts/generate_inspection_report.py --output reports/inspection_2026-05-09.md
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT     = Path(__file__).resolve().parents[1]
BENCH    = ROOT / "bench_results"
REPORTS  = ROOT / "reports"

RESULT_KEYS = {
    "check_calibration":     "캘리브레이션 점검",
    "check_index_integrity": "인덱스 정합성 점검",
    "domain_bench_queries":  "도메인별 쿼리 벤치",
    "test_ocr_search":       "이미지 내 텍스트 검색",
    "test_irrelevant_queries": "부적합 쿼리 필터링",
}


def _latest(key: str) -> Path | None:
    """bench_results/*_{key}.json 중 가장 최신 파일."""
    candidates = sorted(BENCH.glob(f"*_{key}.json"), reverse=True)
    return candidates[0] if candidates else None


def _load(key: str) -> dict | None:
    p = _latest(key)
    if p is None:
        return None
    try:
        return json.loads(p.read_bytes().decode("utf-8", errors="replace"))
    except Exception:
        return None


def _status(ok: bool | None) -> str:
    if ok is True:  return "✅"
    if ok is False: return "⚠️"
    return "❓"


def section_calibration(data: dict) -> str:
    lines = ["## 1. 캘리브레이션 상태\n"]
    lines.append("| 도메인 | abs_thr | mu_null | sigma | FAR | N | method | 상태 |")
    lines.append("|--------|---------|---------|-------|-----|---|--------|------|")

    for domain, d in data.get("trichef", {}).items():
        if domain.startswith("_"):
            continue
        warns = d.get("warnings", [])
        st = "✅" if not warns else "⚠️"
        lines.append(
            f"| {domain} | {d.get('abs_threshold',0):.4f} | {d.get('mu_null',0):.4f} |"
            f" {d.get('sigma_null',0):.4f} | {d.get('far','?')} | {d.get('N','?')} |"
            f" {d.get('method','?')} | {st} |"
        )
        for w in warns:
            lines.append(f"| | | | | | | ⚠ {w} | |")

    bgm = data.get("bgm", {})
    bgm_warns = bgm.get("warnings", [])
    bgm_st = "✅" if not bgm_warns else "⚠️"
    bgm_err = bgm.get("_error", "")
    if bgm_err:
        lines.append(f"| BGM | - | - | - | - | - | {bgm_err} | ⚠️ |")
    else:
        lines.append(
            f"| BGM | - | {bgm.get('mu_null',0):.4f} | {bgm.get('sigma_null',0):.4f}"
            f" | - | {bgm.get('N','?')} | z-score CDF | {bgm_st} |"
        )

    alpha_info = data.get("doc_im_alpha", {})
    cur = alpha_info.get("current", "?")
    rec = alpha_info.get("recommended", 0.20)
    alpha_ok = alpha_info.get("ok", False)
    lines.append(
        f"\n> **DOC\\_IM\\_ALPHA**: 현재 `{cur}` / 권장 `{rec}`"
        f"  {'✅' if alpha_ok else '⚠️ 권장값으로 변경 필요 (config.py:107)'}"
    )

    s = data.get("summary", {})
    lines.append(f"\n> 종합: ✅ OK={s.get('ok',0)}  ⚠️ WARN={s.get('warn',0)}"
                 f"  ❓ MISSING={s.get('missing',0)}\n")
    return "\n".join(lines)


def section_integrity(data: dict) -> str:
    lines = ["## 2. 인덱스 정합성\n"]
    lines.append("| 도메인 | N | Re | Im | Z | ids | sparse | ASF | Im_body/L3 | 상태 |")
    lines.append("|--------|---|----|----|---|-----|--------|-----|------------|------|")

    for domain, d in data.get("domains", {}).items():
        info = d.get("info", {})
        warns = d.get("warnings", [])
        st = "✅" if d.get("ok") else "⚠️"
        n  = info.get("N", "?")
        re_dim = info.get("Re_shape", ["?", "?"])
        im_dim = info.get("Im_shape", ["?", "?"])
        z_dim  = info.get("Z_shape",  ["?", "?"])
        ids_n  = info.get("ids_count", "?")
        sp_nnz = info.get("sparse_nnz")
        sp_str = f"nnz={sp_nnz}" if sp_nnz is not None else "❌"
        asf_n  = info.get("asf_sets_count", "❌")
        # fusion 활성
        fusion = ""
        if info.get("Im_body_exists"):
            fusion = "Im_body✅"
        elif info.get("Im_L3_exists"):
            fusion = "L3✅"
        lines.append(
            f"| {domain} | {n} | {re_dim[1] if len(re_dim)>1 else '?'}d |"
            f" {im_dim[1] if len(im_dim)>1 else '?'}d | {z_dim[1] if len(z_dim)>1 else '?'}d |"
            f" {ids_n} | {sp_str} | {asf_n} | {fusion} | {st} |"
        )
        for w in warns:
            lines.append(f"| ↳ ⚠️ | {w} | | | | | | | | |")

    s = data.get("summary", {})
    lines.append(f"\n> 종합: ✅ OK={s.get('ok',0)}  ⚠️ WARN={s.get('warn',0)}\n")
    return "\n".join(lines)


def section_bench(data: dict) -> str:
    lines = ["## 3. 도메인별 쿼리 성능 (Hit@K)\n"]
    lines.append("| 도메인 | 쿼리수 | Hit@1 | Hit@3 | Hit@5 | 평균Conf | 부적합차단률 |")
    lines.append("|--------|--------|-------|-------|-------|----------|------------|")

    for domain, s in sorted(data.get("summary", {}).items()):
        h1 = s.get("hit_at_1", 0)
        h3 = s.get("hit_at_3", 0)
        h5 = s.get("hit_at_5", 0)
        ac = s.get("avg_top_confidence", 0)
        br = s.get("irrelevant_block_rate", 0)
        rn = s.get("rel_queries", 0)
        # 색상 이모지
        h1s = "✅" if h1 >= 0.6 else ("⚠️" if h1 >= 0.3 else "❌")
        brs = "✅" if br >= 0.8 else ("⚠️" if br >= 0.5 else "❌")
        lines.append(
            f"| {domain} | {rn} | {h1:.1%} {h1s} | {h3:.1%} | {h5:.1%}"
            f" | {ac:.3f} | {br:.1%} {brs} |"
        )

    lines.append("")

    # 미스 쿼리 목록 (Hit@5 실패)
    misses = [
        r for r in data.get("per_query", [])
        if not r.get("irrelevant") and not r.get("hit5", False)
    ]
    if misses:
        lines.append("### 미스 쿼리 (Hit@5 실패)\n")
        for r in misses[:10]:
            lines.append(f"- `{r['domain']}` / `{r['query']}`  conf={r.get('top_conf',0):.3f}")
        lines.append("")

    # 부적합 노출 쿼리
    exposed = [
        r for r in data.get("per_query", [])
        if r.get("irrelevant") and not r.get("blocked", True)
    ]
    if exposed:
        lines.append("### ⚠️ 부적합 쿼리 노출 목록\n")
        for r in exposed[:10]:
            top = r.get("results", [{}])[0].get("id", "") if r.get("results") else ""
            lines.append(
                f"- `{r['domain']}` / `{r['query']}`  "
                f"conf={r.get('top_conf',0):.3f}  → `{top[:50]}`"
            )
        lines.append("")

    return "\n".join(lines)


def section_ocr(data: dict) -> str:
    lines = ["## 4. 이미지·문서 내 텍스트 검색\n"]
    diag = data.get("diagnosis", {})
    ocr_ok  = diag.get("ocr_implemented", False)
    kr_pct  = diag.get("caption_korean_pct", 0)
    hit_rate = diag.get("caption_search_hit_rate", 0)

    lines.append(f"| 항목 | 상태 |")
    lines.append(f"|------|------|")
    lines.append(f"| OCR 구현 | {'✅ 구현됨' if ocr_ok else '❌ 미구현'} |")
    lines.append(f"| 캡션 한국어 비율 | {kr_pct:.1f}% {'✅' if kr_pct>=50 else '⚠️'} |")
    lines.append(f"| 캡션 기반 검색 히트율 | {hit_rate:.1%} {'✅' if hit_rate>=0.5 else '⚠️'} |")
    lines.append("")

    if not ocr_ok:
        lines.append("> **개선 권장**: `scripts/ocr_doc_pages.py` 실행으로 OCR 텍스트 추가."
                     " 이미지 내 한국어 텍스트(연도, 고유명사)는 현재 검색 불가.\n")
    return "\n".join(lines)


def section_irrelevant(data: dict) -> str:
    lines = ["## 5. 부적합 쿼리 필터링\n"]
    lines.append(f"임계값: confidence < {data.get('threshold', 0.40)}\n")
    lines.append("| 도메인 | 차단률 | 평균Conf | fallback 노출 | 상태 |")
    lines.append("|--------|--------|----------|--------------|------|")

    for domain, s in sorted(data.get("per_domain", {}).items()):
        br = s.get("block_rate", 0)
        ac = s.get("avg_conf", 0)
        fb = s.get("fallback_exposed", 0)
        st = "✅" if br >= 0.8 else ("⚠️" if br >= 0.5 else "❌")
        lines.append(
            f"| {domain} | {br:.1%} {st} | {ac:.3f} | {fb}건 | {st} |"
        )

    # fallback 경고
    fb_doms = [
        d for d, s in data.get("per_domain", {}).items()
        if s.get("fallback_exposed", 0) > 0
    ]
    if fb_doms:
        lines.append(f"\n> ⚠️ fallback 노출 도메인: `{'`, `'.join(fb_doms)}`  "
                     "— `unified_engine.py` fallback 조건 강화 검토 필요\n")
    lines.append("")
    return "\n".join(lines)


def section_recommendations(all_data: dict) -> str:
    lines = ["## 6. 개선 권장 사항\n",
             "### 즉시 적용 (코드 1~2줄)\n"]
    recs: list[tuple[str, str]] = []

    # DOC_IM_ALPHA
    alpha_info = all_data.get("calibration", {}).get("doc_im_alpha", {})
    if not alpha_info.get("ok", True):
        cur = alpha_info.get("current", "?")
        recs.append((
            f"`config.py:107` `DOC_IM_ALPHA: {cur} → 0.20`",
            "튜닝 실측 R@5 0.880→0.907 (+2.7pp)"
        ))

    # fallback
    irrel = all_data.get("irrelevant", {}).get("per_domain", {})
    fb_doms = [d for d, s in irrel.items() if s.get("fallback_exposed", 0) > 0]
    if fb_doms:
        recs.append((
            "`unified_engine.py:430` fallback 조건 강화",
            f"부적합 결과 fallback 노출 도메인: {fb_doms}"
        ))

    # BGM calibration
    bgm = all_data.get("calibration", {}).get("bgm", {})
    if bgm.get("_error"):
        recs.append((
            "`scripts/bgm_calibrate.py` 실행",
            "BGM calibration.json 없음 — 기본값 사용 중"
        ))

    # OCR
    ocr_ok = all_data.get("ocr", {}).get("diagnosis", {}).get("ocr_implemented", False)
    if not ocr_ok:
        recs.append((
            "`scripts/ocr_doc_pages.py` 실행",
            "이미지 내 텍스트(한국어) 검색 불가"
        ))

    for i, (action, reason) in enumerate(recs, 1):
        lines.append(f"{i}. **{action}**  \n   → {reason}\n")

    if not recs:
        lines.append("_모든 즉시 적용 항목 정상_\n")

    lines.append("### 중기 적용 (스크립트 재실행)\n")
    lines.append("1. `scripts/tune_doc_im_alpha.py` — 최적 α 재검증 후 config 반영")
    lines.append("2. `DI_TriCHEF/auto_calibration/auto_recalibrate.py` — crossmodal calibration 재실행")
    lines.append("3. `scripts/rebuild_img_qwen_full_caption.py` — Qwen 한국어 캡션 재생성 (L1/L2/L3)")
    lines.append("4. `scripts/rebuild_asf_vocab.py` — ASF vocab 재구축 (한국어 형태소 개선)")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="", help="출력 파일 경로 (기본: reports/)")
    args = parser.parse_args()

    print("[generate_inspection_report] 최신 결과 수집 중...")
    BENCH.mkdir(exist_ok=True)

    all_data: dict = {}
    for key in RESULT_KEYS:
        d = _load(key)
        short = key.split("_")[0]  # 축약 키
        if d:
            all_data[short if short not in all_data else key] = d
            print(f"  ✓ {key}")
        else:
            print(f"  ✗ {key} — 결과 파일 없음 (스크립트 미실행)")

    # 키 재매핑
    data_map = {
        "calibration": _load("check_calibration"),
        "integrity":   _load("check_index_integrity"),
        "bench":       _load("domain_bench_queries"),
        "ocr":         _load("test_ocr_search"),
        "irrelevant":  _load("test_irrelevant_queries"),
    }

    now = datetime.datetime.now()
    md_lines: list[str] = [
        f"# DB_insight 야간 점검 리포트",
        f"> 생성: {now.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 목차",
        "1. [캘리브레이션 상태](#1-캘리브레이션-상태)",
        "2. [인덱스 정합성](#2-인덱스-정합성)",
        "3. [도메인별 쿼리 성능](#3-도메인별-쿼리-성능-hitk)",
        "4. [이미지·문서 내 텍스트 검색](#4-이미지문서-내-텍스트-검색)",
        "5. [부적합 쿼리 필터링](#5-부적합-쿼리-필터링)",
        "6. [개선 권장 사항](#6-개선-권장-사항)",
        "",
    ]

    if data_map["calibration"]:
        md_lines.append(section_calibration(data_map["calibration"]))
    else:
        md_lines.append("## 1. 캘리브레이션 상태\n> ⚠️ check_calibration.py 미실행\n")

    if data_map["integrity"]:
        md_lines.append(section_integrity(data_map["integrity"]))
    else:
        md_lines.append("## 2. 인덱스 정합성\n> ⚠️ check_index_integrity.py 미실행\n")

    if data_map["bench"]:
        md_lines.append(section_bench(data_map["bench"]))
    else:
        md_lines.append("## 3. 도메인별 쿼리 성능\n> ⚠️ domain_bench_queries.py 미실행\n")

    if data_map["ocr"]:
        md_lines.append(section_ocr(data_map["ocr"]))
    else:
        md_lines.append("## 4. 이미지·문서 내 텍스트 검색\n> ⚠️ test_ocr_search.py 미실행\n")

    if data_map["irrelevant"]:
        md_lines.append(section_irrelevant(data_map["irrelevant"]))
    else:
        md_lines.append("## 5. 부적합 쿼리 필터링\n> ⚠️ test_irrelevant_queries.py 미실행\n")

    md_lines.append(section_recommendations(data_map))

    md_content = "\n".join(md_lines)

    if args.output:
        out = Path(args.output)
    else:
        REPORTS.mkdir(exist_ok=True)
        ts  = now.strftime("%Y%m%d_%H%M%S")
        out = REPORTS / f"inspection_{ts}.md"

    out.write_text(md_content, encoding="utf-8")
    print(f"\n[리포트 저장] {out}")

    # 콘솔 요약 미리보기
    print("\n" + "=" * 65)
    print("요약 미리보기 (첫 40줄)")
    print("=" * 65)
    for line in md_content.splitlines()[:40]:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
