"""scripts/extract_caption_lies_by_category.py — 캡션 거짓말 키워드별 분류 추출.

기존 real_caption_lies_v2.json (또는 직접 측정) 활용하여:
  1. threshold 0.10 으로 재필터 (0.20 너무 관대 → 거의 전부, 0.05 너무 엄격 → 일부만)
  2. 카테고리별 분리: cat / dog / person / building / food / 기타
  3. 각 카테고리별 separate 파일 생성

산출물:
  scripts/lies_by_category/cat_lies.json (사자상 등 가짜 cat 캡션)
  scripts/lies_by_category/dog_lies.json (강아지 아닌데 dog)
  scripts/lies_by_category/person_lies.json
  scripts/lies_by_category/building_lies.json
  scripts/lies_by_category/food_lies.json
  scripts/lies_by_category/other_lies.json
  scripts/lies_by_category/summary.md

사용:
  python scripts/extract_caption_lies_by_category.py [--threshold 0.10]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))


# 카테고리 매핑 — 키워드 in 캡션 = 그 카테고리
CATEGORIES = {
    "cat": ["cat", "kitten", "feline", "고양이"],
    "dog": ["dog", "puppy", "canine", "강아지"],
    "person": ["person", "people", "man", "woman", "child", "사람"],
    "building": ["building", "house", "structure", "건물", "집"],
    "food": ["food", "plate", "meal", "dish", "음식", "요리"],
    "vehicle": ["car", "vehicle", "boat", "ship", "plane", "자동차", "차"],
    "nature": ["mountain", "ocean", "river", "tree", "산", "바다"],
}


def categorize(caption: str) -> str:
    """캡션을 카테고리로 분류. 매칭되는 카테고리 중 첫 번째 반환."""
    cap_lower = caption.lower()
    for cat, keywords in CATEGORIES.items():
        for kw in keywords:
            if kw in cap_lower:
                return cat
    return "other"


def measure_all_cosines() -> list[dict]:
    """전체 이미지 SigLIP2 시각-캡션 cosine 직접 측정 (threshold 무관 전체)."""
    import numpy as np
    from config import PATHS
    from embedders.trichef import siglip2_re

    idir = Path(PATHS["TRICHEF_IMG_CACHE"])
    img_emb = np.load(str(idir / "cache_img_Re_siglip2.npy"))
    norms = np.linalg.norm(img_emb, axis=1, keepdims=True)
    img_emb = (img_emb / np.maximum(norms, 1e-8)).astype(np.float32, copy=False)
    ids_data = json.loads((idir / "img_ids.json").read_text(encoding="utf-8"))
    ids = ids_data.get("ids") if isinstance(ids_data, dict) else ids_data
    N = len(ids)
    logger.info(f"이미지: {N}개")

    captions = json.loads((idir / "caption_3stage.json").read_text(encoding="utf-8"))
    cap_ids = captions.get("ids", [])
    L1_list = captions.get("L1", [])
    L2_list = captions.get("L2", [])
    L3_list = captions.get("L3", [])

    cap_dict = {}
    for j, cid in enumerate(cap_ids):
        l1 = L1_list[j] if j < len(L1_list) else ""
        l2 = L2_list[j] if j < len(L2_list) else ""
        l3 = L3_list[j] if j < len(L3_list) else ""
        cap = (str(l1) + " " + str(l2) + " " + str(l3)).strip()
        cap_dict[cid] = cap

    items = []
    for i, _id in enumerate(ids):
        cap = cap_dict.get(_id, "")
        if cap and len(cap) >= 10:
            items.append((i, _id, cap))
    logger.info(f"캡션 있는 이미지: {len(items)}개")

    all_results = []
    batch = 64
    for batch_start in range(0, len(items), batch):
        batch_items = items[batch_start: batch_start + batch]
        batch_caps = [it[2] for it in batch_items]
        batch_indices = [it[0] for it in batch_items]
        batch_ids_b = [it[1] for it in batch_items]
        try:
            txt_emb = siglip2_re.embed_texts(batch_caps)
            txt_emb = np.asarray(txt_emb, dtype=np.float32)
            norms2 = np.linalg.norm(txt_emb, axis=1, keepdims=True)
            txt_emb = txt_emb / np.maximum(norms2, 1e-8)
        except Exception:
            continue
        img_batch = img_emb[batch_indices]
        cos = np.einsum("ij,ij->i", img_batch, txt_emb)
        for _id, cap, c in zip(batch_ids_b, batch_caps, cos):
            all_results.append({"id": _id, "caption": cap, "cosine": float(c)})
        if batch_start % 320 == 0:
            logger.info(f"  진행: {batch_start}/{len(items)}")

    return all_results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.10,
                        help="거짓 캡션 cosine 임계값 (default: 0.10)")
    args = parser.parse_args()

    logger.info("═" * 60)
    logger.info(f"캡션 거짓말 키워드별 분류 추출 (threshold={args.threshold})")
    logger.info("═" * 60)

    all_results = measure_all_cosines()
    logger.info(f"\n전체 측정: {len(all_results)}개 이미지")

    # cosine 분포 통계
    if all_results:
        import numpy as np
        cosines = np.asarray([r["cosine"] for r in all_results])
        logger.info(f"cosine 분포: "
                    f"min={cosines.min():.3f}, max={cosines.max():.3f}, "
                    f"mean={cosines.mean():.3f}, median={np.median(cosines):.3f}")
        for thr in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]:
            n = (cosines < thr).sum()
            logger.info(f"  cosine < {thr}: {n}건 ({n/len(cosines)*100:.1f}%)")

    # threshold 적용
    suspects = [r for r in all_results if r["cosine"] < args.threshold]
    suspects.sort(key=lambda x: x["cosine"])
    logger.info(f"\nthreshold {args.threshold} 미만: {len(suspects)}건")

    # 카테고리별 분류
    by_category = {cat: [] for cat in list(CATEGORIES.keys()) + ["other"]}
    for s in suspects:
        cat = categorize(s["caption"])
        by_category[cat].append(s)

    # 출력 디렉터리
    out_dir = _BACKEND_DIR / "scripts" / "lies_by_category"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("\n=== 카테고리별 거짓 캡션 ===")
    summary = {"threshold": args.threshold, "total": len(suspects), "by_category": {}}
    for cat, items in by_category.items():
        logger.info(f"  {cat}: {len(items)}건")
        out_path = out_dir / f"{cat}_lies.json"
        out_path.write_text(json.dumps({
            "category": cat,
            "n": len(items),
            "items": items[:300],   # top 300
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        summary["by_category"][cat] = len(items)

    # 마크다운 요약
    md = [f"# 캡션 거짓말 카테고리별 분석 (threshold={args.threshold})\n\n"]
    md.append(f"전체 측정: {len(all_results)}개\n")
    md.append(f"의심 (cosine < {args.threshold}): **{len(suspects)}건**\n\n")

    md.append("## 카테고리별 분포\n\n")
    md.append("| 카테고리 | 건수 | 키워드 |\n")
    md.append("|---------|------|--------|\n")
    for cat in list(CATEGORIES.keys()) + ["other"]:
        kws = ", ".join(CATEGORIES.get(cat, [])) if cat in CATEGORIES else "—"
        md.append(f"| **{cat}** | {summary['by_category'][cat]} | {kws} |\n")

    md.append("\n## 카테고리별 Top 5 (가장 명백한 거짓)\n\n")
    for cat, items in by_category.items():
        if not items:
            continue
        md.append(f"### {cat}\n")
        for i, s in enumerate(items[:5], 1):
            md.append(f"{i}. **[{s['cosine']:.3f}]** `{s['id'][:60]}`\n")
            md.append(f"   - {s['caption'][:120]}\n")
        md.append("\n")

    md.append("## 우선 정제 권장\n\n")
    sorted_cats = sorted(summary["by_category"].items(), key=lambda x: -x[1])
    for cat, n in sorted_cats[:5]:
        md.append(f"- **{cat}** {n}건 — 데이터셋 정제 시 우선 검토\n")

    md_path = out_dir / "summary.md"
    md_path.write_text("".join(md), encoding="utf-8")
    logger.info(f"\n저장: {out_dir}")
    logger.info(f"  ↳ summary.md")
    for cat in by_category:
        logger.info(f"  ↳ {cat}_lies.json ({summary['by_category'][cat]}건)")
    logger.info("═" * 60)


if __name__ == "__main__":
    main()
