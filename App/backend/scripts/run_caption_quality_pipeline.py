"""scripts/run_caption_quality_pipeline.py — 캡션 품질 파이프라인 (Option A).

자동 실행 (~10분):
  1.5. HTML 리포트 생성 — cat/dog/food/person 등 카테고리별 시각 검토용
  2. 캡션 품질 마킹 — caption_quality.json 신규 (원본 보존)
  3. 우선순위 분석 — 카테고리별 정제 시급도 자동 도출

산출물:
  scripts/lies_by_category/preview.html (사용자 시각 검토)
  scripts/caption_quality.json (마킹 데이터)
  scripts/caption_priority_analysis.md (정제 우선순위)

사용:
  cd App/backend
  python scripts/run_caption_quality_pipeline.py
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = _BACKEND_DIR / "scripts"
LIES_DIR = SCRIPTS_DIR / "lies_by_category"
sys.path.insert(0, str(_BACKEND_DIR))


# ─── Step 1.5 — HTML 리포트 ───────────────────────────────────────────────────
def step1_html_report():
    logger.info("═" * 60)
    logger.info("[1/3] HTML 시각 검토 리포트 생성")
    logger.info("═" * 60)

    if not LIES_DIR.exists():
        logger.error(f"  {LIES_DIR} 없음 — extract_caption_lies_by_category.py 먼저 실행 필요")
        return

    from config import PATHS
    raw_db = Path(PATHS["RAW_DB"])

    html_parts = ["""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>캡션 거짓말 시각 검토</title>
<style>
body { font-family: 'Malgun Gothic', sans-serif; background: #1a1a1a; color: #e0e0e0; padding: 20px; }
h1 { color: #4caf50; }
h2 { color: #ff9800; border-bottom: 2px solid #555; padding-bottom: 10px; margin-top: 40px; }
.item { display: flex; gap: 15px; margin: 15px 0; padding: 10px; background: #2a2a2a; border-radius: 8px; }
.item img { width: 200px; height: 150px; object-fit: cover; border-radius: 4px; }
.info { flex: 1; }
.cosine { color: #f44336; font-weight: bold; font-size: 14px; }
.id { color: #888; font-size: 12px; word-break: break-all; }
.cap { color: #ddd; margin-top: 8px; line-height: 1.4; }
.summary { background: #2a4a2a; padding: 15px; border-radius: 8px; margin: 20px 0; }
</style></head><body>
<h1>캡션 거짓말 시각 검토 — 카테고리별 Top 30</h1>
<p class="summary">cosine < 0.05 인 명백한 거짓 캡션. 이미지가 캡션과 일치하는지 직접 확인.</p>
"""]

    for category in ["cat", "dog", "food", "person", "building", "vehicle", "nature", "other"]:
        cat_path = LIES_DIR / f"{category}_lies.json"
        if not cat_path.exists():
            continue
        data = json.loads(cat_path.read_text(encoding="utf-8"))
        items = data.get("items", [])
        n = data.get("n", 0)
        if not items:
            continue

        html_parts.append(f"<h2>{category} — {n}건 (Top 30)</h2>\n")
        for s in items[:30]:
            rid = s.get("id", "")
            img_path = (raw_db / "Img" / rid).as_posix()
            file_url = f"file:///{img_path}"
            cosine = s.get("cosine", 0)
            cap = s.get("caption", "").replace("<", "&lt;").replace(">", "&gt;")
            html_parts.append(
                f'<div class="item">'
                f'<img src="{file_url}" alt="img" onerror="this.style.display=\'none\'">'
                f'<div class="info">'
                f'<span class="cosine">cosine={cosine:.3f}</span>'
                f'<div class="id">{rid}</div>'
                f'<div class="cap">{cap}</div>'
                f'</div></div>\n'
            )

    html_parts.append("</body></html>")

    out = LIES_DIR / "preview.html"
    out.write_text("".join(html_parts), encoding="utf-8")
    logger.info(f"  → {out}")
    logger.info(f"  ↳ 더블클릭하여 이미지 + 캡션 시각 검토 가능")


# ─── Step 2 — 캡션 품질 마킹 ──────────────────────────────────────────────────
def step2_quality_marking() -> dict:
    logger.info("═" * 60)
    logger.info("[2/3] 캡션 품질 마킹 (caption_quality.json — 원본 보존)")
    logger.info("═" * 60)

    quality = {}
    for category in ["cat", "dog", "food", "person", "building", "vehicle", "nature", "other"]:
        cat_path = LIES_DIR / f"{category}_lies.json"
        if not cat_path.exists():
            continue
        data = json.loads(cat_path.read_text(encoding="utf-8"))
        items = data.get("items", [])
        for s in items:
            quality[s["id"]] = {
                "suspicious": True,
                "cosine": s.get("cosine"),
                "category": category,
                "caption": s.get("caption", "")[:200],
            }

    out = SCRIPTS_DIR / "caption_quality.json"
    out.write_text(json.dumps({
        "version": "v1",
        "method": "siglip2_visual_text_cosine",
        "threshold": 0.05,
        "n_marked": len(quality),
        "items": quality,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"  → 마킹 {len(quality)}건 (caption_3stage.json 원본 보존)")
    logger.info(f"  → {out}")

    return {"n_marked": len(quality)}


# ─── Step 3 — 우선순위 분석 ──────────────────────────────────────────────────
def step3_priority_analysis() -> dict:
    logger.info("═" * 60)
    logger.info("[3/3] 카테고리별 정제 우선순위 분석")
    logger.info("═" * 60)

    counts = {}
    for category in ["cat", "dog", "food", "person", "building", "vehicle", "nature", "other"]:
        cat_path = LIES_DIR / f"{category}_lies.json"
        if cat_path.exists():
            data = json.loads(cat_path.read_text(encoding="utf-8"))
            counts[category] = data.get("n", 0)

    total = sum(counts.values())
    sorted_cats = sorted(counts.items(), key=lambda x: -x[1])

    md = ["# 캡션 정제 우선순위 분석\n\n",
          f"실행: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
          f"전체 거짓 캡션: **{total}건** (threshold cosine < 0.05)\n\n",
          "## 카테고리별 우선순위\n\n",
          "| 순위 | 카테고리 | 건수 | 비율 | 권장 액션 |\n",
          "|------|---------|------|------|----------|\n"]

    actions = {
        "food": "Qwen 음식 분류 정확도 개선 — 가장 시급",
        "other": "추가 키워드 분류 또는 수동 검토",
        "cat": "사자상/인형 등 시각적 유사 객체와 분리 학습 필요",
        "person": "사람 검출 정확도 개선",
        "nature": "자연 풍경 캡션 보강",
        "building": "건물 vs 인테리어 분리",
        "vehicle": "차량 종류 세분화",
        "dog": "강아지 vs 다른 동물 분리",
    }

    for i, (cat, n) in enumerate(sorted_cats, 1):
        pct = n / max(total, 1) * 100
        md.append(f"| {i} | **{cat}** | {n} | {pct:.1f}% | {actions.get(cat, '검토')} |\n")

    md.append("\n## 시급도 분류\n\n")
    md.append("### ⭐⭐⭐ 매우 시급 (200건+)\n")
    for cat, n in sorted_cats:
        if n >= 200:
            md.append(f"- **{cat}**: {n}건 — 데이터셋 정제 1순위\n")

    md.append("\n### ⭐⭐ 시급 (100~200건)\n")
    for cat, n in sorted_cats:
        if 100 <= n < 200:
            md.append(f"- **{cat}**: {n}건\n")

    md.append("\n### ⭐ 중간 (50~100건)\n")
    for cat, n in sorted_cats:
        if 50 <= n < 100:
            md.append(f"- **{cat}**: {n}건\n")

    md.append("\n### 낮음 (50건 미만)\n")
    for cat, n in sorted_cats:
        if n < 50:
            md.append(f"- {cat}: {n}건\n")

    md.append("\n## 권장 후속 작업\n\n")
    md.append("1. `lies_by_category/preview.html` 시각 검토 → 진짜 거짓 확인\n")
    md.append("2. `caption_quality.json` 의 마킹된 이미지 → Qwen 재캡션 또는 캡션 폐기\n")
    md.append("3. 인덱싱 시점 캡션 검증 도입 (Phase H — 별도 코드 변경)\n")
    md.append("4. visual_check.py 에 caption_quality 활용 옵션 추가 (선택)\n")

    out_path = SCRIPTS_DIR / "caption_priority_analysis.md"
    out_path.write_text("".join(md), encoding="utf-8")
    logger.info(f"  → {out_path}")

    for cat, n in sorted_cats[:5]:
        logger.info(f"  [{cat}] {n}건 — {actions.get(cat, '검토')}")

    return {"counts": dict(sorted_cats), "total": total}


# ─── 메인 ────────────────────────────────────────────────────────────────────
def main():
    logger.info("═" * 60)
    logger.info("캡션 품질 파이프라인 (Option A) 시작")
    logger.info("═" * 60)
    t0 = time.time()

    step1_html_report()
    quality_stats = step2_quality_marking()
    priority = step3_priority_analysis()

    logger.info("═" * 60)
    logger.info(f"전체 완료 — 소요 {time.time()-t0:.1f}초")
    logger.info("산출물:")
    logger.info("  scripts/lies_by_category/preview.html (시각 검토용)")
    logger.info("  scripts/caption_quality.json (마킹 데이터)")
    logger.info("  scripts/caption_priority_analysis.md (정제 우선순위)")
    logger.info("═" * 60)
    logger.info(f"\n총 {quality_stats['n_marked']}건 거짓 캡션 마킹 완료")
    logger.info(f"카테고리별 분포: {priority.get('counts', {})}")


if __name__ == "__main__":
    main()
