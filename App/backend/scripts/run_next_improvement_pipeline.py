"""scripts/run_next_improvement_pipeline.py — 다음 세션 통합 개선 파이프라인.

자동 sequential 실행 (~1.5~2h):
  1. 오버나이트 파이프라인 재실행 (한글 폰트 패치 포함, BGM 회귀 수정 반영)
  2. 캡션 거짓말 정밀 추출 — "(no caption)" 제외, 진짜 거짓말만 골라냄
  3. n_sigma sweep 결과 분석 — 도메인별 권장 n 자동 도출
  4. 통합 분석 리포트 생성

산출물:
  scripts/overnight_report.json (재생성)
  scripts/caption_mismatch_suspects.json (재생성)
  scripts/calibration_distributions.png (한글 정상 표시)
  scripts/real_caption_lies.json (NEW — 진짜 거짓말만)
  scripts/n_sigma_recommendations.json (NEW — 도메인별 권장 n)
  scripts/next_improvement_summary.md (NEW — 사람 친화 요약)

사용:
  cd App/backend
  python scripts/run_next_improvement_pipeline.py
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = _BACKEND_DIR / "scripts"


# ─── Step 1: 오버나이트 파이프라인 실행 ───────────────────────────────────────
def step1_run_overnight() -> bool:
    logger.info("═" * 60)
    logger.info("[1/4] 오버나이트 파이프라인 재실행 (한글 폰트 패치 + BGM 수정 반영)")
    logger.info("═" * 60)
    t0 = time.time()
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "run_overnight_pipeline.py")],
            cwd=str(_BACKEND_DIR),
            check=False,
            capture_output=False,  # stdout 직접 보임
        )
        elapsed = time.time() - t0
        logger.info(f"  ↳ 오버나이트 완료: {elapsed:.1f}s, exit code {result.returncode}")
        return result.returncode == 0
    except Exception as e:
        logger.exception(f"  실패: {e}")
        return False


# ─── Step 2: 캡션 거짓말 정밀 추출 ────────────────────────────────────────────
def step2_filter_caption_lies() -> dict:
    logger.info("═" * 60)
    logger.info("[2/4] 캡션 거짓말 정밀 추출 (no caption 제외)")
    logger.info("═" * 60)

    susp_path = SCRIPTS_DIR / "caption_mismatch_suspects.json"
    if not susp_path.exists():
        logger.warning(f"  {susp_path} 없음 — Step 1 실패 의심")
        return {"error": "suspects file missing"}

    data = json.loads(susp_path.read_text(encoding="utf-8"))
    suspects = data.get("suspects", [])
    n_total = data.get("n_total", 0)
    n_suspects = data.get("n_suspects", 0)

    # 카테고리 분류
    real_lies = []      # 캡션 있으면서 cosine 낮음 — 진짜 거짓말
    no_captions = []    # "(no caption)" — 캡션 누락
    other = []          # 기타 (짧은 캡션 등)

    for s in suspects:
        cap = s.get("caption", "").strip()
        if not cap or cap == "(no caption)":
            no_captions.append(s)
        elif len(cap) < 10:
            other.append(s)
        else:
            real_lies.append(s)

    logger.info(f"  전체 의심: {len(suspects)}건 (전체 이미지 {n_total}개 중 {n_suspects}건)")
    logger.info(f"    캡션 누락 (no caption): {len(no_captions)}건")
    logger.info(f"    캡션 너무 짧음 (<10자): {len(other)}건")
    logger.info(f"    🚨 진짜 거짓 캡션: {len(real_lies)}건")

    # 진짜 거짓 캡션 — 패턴 분석
    if real_lies:
        logger.info(f"\n  진짜 거짓 캡션 Top 10:")
        for i, s in enumerate(real_lies[:10], 1):
            logger.info(f"    {i:2d}. [{s['cosine']:.3f}] {s['id'][:50]}")
            logger.info(f"        캡션: {s['caption'][:80]}")

        # 키워드 분석 — 어떤 거짓 키워드가 자주 나오나
        keywords = Counter()
        for s in real_lies:
            cap = s["caption"].lower()
            for kw in ["고양이", "강아지", "사람", "음식", "건물", "하늘", "차", "꽃",
                       "cat", "dog", "person", "building", "flower", "car"]:
                if kw in cap:
                    keywords[kw] += 1
        if keywords:
            logger.info(f"\n  거짓 캡션 빈출 키워드: {keywords.most_common(10)}")

    # 저장
    out_path = SCRIPTS_DIR / "real_caption_lies.json"
    out_path.write_text(
        json.dumps({
            "n_total_images": n_total,
            "n_total_suspects": len(suspects),
            "n_real_lies": len(real_lies),
            "n_no_captions": len(no_captions),
            "n_other": len(other),
            "real_lies": real_lies[:200],   # top 200
            "no_captions_sample": no_captions[:50],
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"\n  저장: {out_path}")

    return {
        "n_real_lies": len(real_lies),
        "n_no_captions": len(no_captions),
        "n_other": len(other),
    }


# ─── Step 3: n_sigma sweep 분석 ──────────────────────────────────────────────
def step3_analyze_n_sigma() -> dict:
    logger.info("═" * 60)
    logger.info("[3/4] n_sigma sweep 결과 분석")
    logger.info("═" * 60)

    report_path = SCRIPTS_DIR / "overnight_report.json"
    if not report_path.exists():
        logger.warning(f"  {report_path} 없음 — Step 1 실패 의심")
        return {"error": "overnight report missing"}

    report = json.loads(report_path.read_text(encoding="utf-8"))
    sweep_data = report.get("phase3_n_sigma_sweep", {})
    if not sweep_data:
        logger.warning("  phase3_n_sigma_sweep 데이터 없음")
        return {"error": "no sweep data"}

    # 도메인별 분석
    # 평가 기준:
    #   - 적합 쿼리 (예: image='고양이') 의 결과 수가 충분
    #   - 무관 쿼리 (예: image='보이저호') 의 결과 수가 0 이상적
    # 이상적인 n: 적합/무관 분리도 최대화
    recommendations = {}

    for domain, n_results in sweep_data.items():
        domain_analysis = {}
        for n_key, queries in n_results.items():
            n_val = float(n_key.replace("n_", ""))
            total_n = sum(q.get("n", 0) for q in queries.values() if q)
            n_zero = sum(1 for q in queries.values() if q and q.get("n", 0) == 0)
            domain_analysis[n_val] = {
                "total_results": total_n,
                "queries_with_zero": n_zero,
                "queries": queries,
            }

        # 추천: 무관 쿼리 차단 (zero count 높음) + 적합 쿼리 결과 보존 균형
        if domain_analysis:
            # 가중치: zero_count (무관 차단) 양수, total_results (적합 보존) 양수
            # 도메인별 정상 매칭 쿼리 수 알기 어려워 단순 비율 사용
            best_n = max(domain_analysis.keys(), key=lambda n: (
                domain_analysis[n]["queries_with_zero"],
                -abs(domain_analysis[n]["total_results"] - 30)  # 30 부근이 균형
            ))
            recommendations[domain] = {
                "recommended_n": best_n,
                "all_n": domain_analysis,
            }
            logger.info(f"  [{domain}] 권장 n={best_n}σ "
                        f"(zero_queries={domain_analysis[best_n]['queries_with_zero']}, "
                        f"total_results={domain_analysis[best_n]['total_results']})")

    out_path = SCRIPTS_DIR / "n_sigma_recommendations.json"
    out_path.write_text(json.dumps(recommendations, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    logger.info(f"\n  저장: {out_path}")
    return recommendations


# ─── Step 4: 통합 요약 마크다운 ───────────────────────────────────────────────
def step4_summary(caption_stats: dict, n_sigma_recs: dict):
    logger.info("═" * 60)
    logger.info("[4/4] 통합 요약 마크다운 생성")
    logger.info("═" * 60)

    md = ["# 다음 세션 개선 파이프라인 — 통합 요약\n",
          f"실행 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"]

    # 캡션 거짓말 결과
    md.append("## 1. 캡션 거짓말 분석\n\n")
    if "error" in caption_stats:
        md.append(f"⚠️ {caption_stats['error']}\n\n")
    else:
        md.append(f"- **진짜 거짓 캡션**: {caption_stats.get('n_real_lies', 0)}건\n")
        md.append(f"- 캡션 누락: {caption_stats.get('n_no_captions', 0)}건\n")
        md.append(f"- 캡션 너무 짧음: {caption_stats.get('n_other', 0)}건\n\n")
        md.append("→ 자세한 내용: `scripts/real_caption_lies.json`\n\n")

    # n_sigma 권장
    md.append("## 2. n_sigma 권장 임계치 (도메인별)\n\n")
    md.append("| 도메인 | 권장 n | 무관 차단 | 적합 보존 |\n")
    md.append("|--------|--------|-----------|----------|\n")
    if "error" not in n_sigma_recs:
        for domain, rec in n_sigma_recs.items():
            n = rec.get("recommended_n")
            details = rec.get("all_n", {}).get(n, {})
            md.append(f"| {domain} | {n}σ | "
                      f"{details.get('queries_with_zero', '?')} 쿼리 0건 | "
                      f"{details.get('total_results', '?')} 총 결과 |\n")
    md.append("\n→ 자세한 내용: `scripts/n_sigma_recommendations.json`\n\n")

    # 다음 작업
    md.append("## 3. 다음 작업 권장\n\n")
    md.append("1. 진짜 거짓 캡션 리스트 수동 검토 → 재캡션 또는 캡션 폐기\n")
    md.append("2. 권장 n 값을 visual_check.py / audio_check.py 에 적용\n")
    md.append("3. bgm_check.py / doc_check.py 모듈 작성 (필요 시)\n")
    md.append("4. H 인덱싱 시점 캡션 검증 도입 (근본 해결)\n")

    out_path = SCRIPTS_DIR / "next_improvement_summary.md"
    out_path.write_text("".join(md), encoding="utf-8")
    logger.info(f"  저장: {out_path}")


# ─── 메인 ────────────────────────────────────────────────────────────────────
def main():
    logger.info("═" * 60)
    logger.info("다음 세션 통합 개선 파이프라인 시작")
    logger.info("═" * 60)
    t0 = time.time()

    # Step 1: 오버나이트 재실행
    overnight_ok = step1_run_overnight()
    if not overnight_ok:
        logger.error("오버나이트 실패 — Step 2/3 skip")
        sys.exit(1)

    # Step 2: 캡션 거짓말 정밀 추출
    caption_stats = step2_filter_caption_lies()

    # Step 3: n_sigma sweep 분석
    n_sigma_recs = step3_analyze_n_sigma()

    # Step 4: 통합 요약
    step4_summary(caption_stats, n_sigma_recs)

    elapsed = time.time() - t0
    logger.info("═" * 60)
    logger.info(f"전체 완료 — 소요 {elapsed/60:.1f}분")
    logger.info("산출물:")
    logger.info("  scripts/overnight_report.json (전체 오버나이트 결과)")
    logger.info("  scripts/caption_mismatch_suspects.json (220건 의심)")
    logger.info("  scripts/real_caption_lies.json (진짜 거짓말만)")
    logger.info("  scripts/n_sigma_recommendations.json (권장 임계치)")
    logger.info("  scripts/calibration_distributions.png (한글 정상)")
    logger.info("  scripts/next_improvement_summary.md (사람 친화 요약)")
    logger.info("═" * 60)


if __name__ == "__main__":
    main()
