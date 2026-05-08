"""scripts/recaption_food_v2.py — food 카테고리 305건 재캡션 (~1.5h).

  1. caption_quality.json 에서 category=food 선택
  2. Qwen2.5-VL-3B 로 5-stage 재캡션 (in-memory)
  3. 신규 SigLIP2 cosine 측정 → 기존 vs 신규 비교
  4. caption_food_v2.json 저장 (원본 caption_3stage.json 보존)
  5. 진행 중 incremental save (resume 가능)

⚠️ 원본 caption_3stage.json 변경 없음. swap 은 별도 스크립트로 사용자 승인 후.
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
PROJECT_ROOT = _BACKEND_DIR.parent.parent
sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "DI_TriCHEF"))

OUT_PATH = SCRIPTS_DIR / "caption_food_v2.json"
CKPT_PATH = SCRIPTS_DIR / "caption_food_v2_ckpt.json"

PROMPTS = {
    "title":    "이 사진의 핵심을 1줄로 한국어로 표현하세요. 객체와 핵심 행동만 간결하게.",
    "tagline":  "이 사진의 분위기, 감정, 시각적 인상을 한국어로 1~2문장으로 묘사하세요.",
    "synopsis": "이 사진을 한국어로 자세히 묘사하세요. 주요 객체, 인물 유무, 행동, 위치, 색감, 분위기를 3~5문장으로.",
    "tags_kr":  "이 사진을 표현하는 한국어 키워드를 10~20개 쉼표로 구분하여 출력하세요.",
    "tags_en":  "Output 10~20 English keywords separated by commas describing this image.",
}
MAX_NEW = {"title": 30, "tagline": 60, "synopsis": 150, "tags_kr": 80, "tags_en": 80}


def join_caption(parts: dict) -> str:
    l1 = parts.get("title", "")
    l2 = (parts.get("tagline", "") + " " + parts.get("tags_kr", "")).strip()
    l3 = (parts.get("synopsis", "") + " " + parts.get("tags_en", "")).strip()
    return (l1 + " " + l2 + " " + l3).strip()


def main():
    logger.info("═" * 60)
    logger.info("food 카테고리 305건 재캡션 — v2")
    logger.info("═" * 60)
    t0 = time.time()

    # 1) food IDs 추출
    quality = json.loads((SCRIPTS_DIR / "caption_quality.json").read_text(encoding="utf-8"))
    food_ids = [k for k, v in quality.get("items", {}).items() if v.get("category") == "food"]
    logger.info(f"  food 후보: {len(food_ids)}건")

    # 기존 cosine 매핑 (real_caption_lies.json 우선, 없으면 caption_quality.json 의 것)
    old_cos = {}
    for k, v in quality.get("items", {}).items():
        if v.get("category") == "food":
            old_cos[k] = float(v.get("cosine") or 0)

    # 2) checkpoint resume
    done = {}
    if CKPT_PATH.exists():
        try:
            done = json.loads(CKPT_PATH.read_text(encoding="utf-8"))
            logger.info(f"  체크포인트 로드: {len(done)}건 완료")
        except Exception:
            done = {}

    todo = [rid for rid in food_ids if rid not in done]
    logger.info(f"  잔여: {len(todo)}건")

    # 3) 이미지 경로
    from config import PATHS
    raw_img_dir = Path(PATHS["RAW_DB"]) / "Img"

    # 4) Qwen 로드
    if todo:
        logger.info("\n  Qwen2.5-VL-3B 로드 중...")
        from captioner.qwen_vl_ko import QwenKoCaptioner
        from PIL import Image
        cap = QwenKoCaptioner(dtype="float16")
        cap._load()
        logger.info("  로드 완료")
    else:
        cap = None
        from PIL import Image

    # 5) 재캡션 — incremental save (50건마다)
    save_every = 50
    n_processed = 0
    for i, rid in enumerate(todo, 1):
        img_path = raw_img_dir / rid
        if not img_path.exists():
            done[rid] = {"error": "image not found"}
            continue
        try:
            pil_img = Image.open(str(img_path)).convert("RGB")
        except Exception as e:
            done[rid] = {"error": f"PIL load failed: {e}"}
            continue
        parts = {}
        for stage, prompt in PROMPTS.items():
            try:
                txt = cap.caption(pil_img, prompt=prompt,
                                   max_new_tokens=MAX_NEW[stage])
                parts[stage] = (txt or "").strip()
            except Exception as e:
                parts[stage] = ""
                logger.warning(f"  [{i}] {rid} {stage} 실패: {e}")
        done[rid] = {"parts": parts, "caption": join_caption(parts)}
        n_processed += 1

        if i % 10 == 0:
            elapsed = time.time() - t0
            remain = (len(todo) - i) * (elapsed / max(i, 1))
            logger.info(f"  [{i}/{len(todo)}] {rid[:40]} — "
                        f"경과 {elapsed/60:.1f}분, 잔여 ~{remain/60:.1f}분")

        if i % save_every == 0:
            CKPT_PATH.write_text(json.dumps(done, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
            logger.info(f"    체크포인트 저장 ({i}건)")

    # 최종 저장
    CKPT_PATH.write_text(json.dumps(done, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"\n  재캡션 완료: {n_processed}건 신규")

    # 6) Qwen 메모리 해제 (SigLIP2 위해)
    if cap is not None:
        try:
            del cap
            import gc, torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("  Qwen unload — GPU 메모리 정리")
        except Exception:
            pass

    # 7) SigLIP2 cosine 재측정
    logger.info("\n  SigLIP2 cosine 재측정...")
    import numpy as np
    from embedders.trichef import siglip2_re

    cache_dir = Path(PATHS["TRICHEF_IMG_CACHE"])
    img_emb = np.load(str(cache_dir / "cache_img_Re_siglip2.npy"))
    norms = np.linalg.norm(img_emb, axis=1, keepdims=True)
    img_emb = (img_emb / np.maximum(norms, 1e-8)).astype(np.float32, copy=False)
    ids_data = json.loads((cache_dir / "img_ids.json").read_text(encoding="utf-8"))
    all_ids = ids_data.get("ids") if isinstance(ids_data, dict) else ids_data
    id_to_row = {_id: i for i, _id in enumerate(all_ids)}

    valid = [(rid, d) for rid, d in done.items()
             if isinstance(d, dict) and d.get("caption") and rid in id_to_row]
    captions_new = [d["caption"] for _, d in valid]

    new_cos_map = {}
    batch = 64
    for bs in range(0, len(captions_new), batch):
        chunk = captions_new[bs: bs + batch]
        chunk_ids = [valid[bs + j][0] for j in range(len(chunk))]
        try:
            txt_emb = siglip2_re.embed_texts(chunk)
            txt_emb = np.asarray(txt_emb, dtype=np.float32)
            norms2 = np.linalg.norm(txt_emb, axis=1, keepdims=True)
            txt_emb = txt_emb / np.maximum(norms2, 1e-8)
            for j, rid in enumerate(chunk_ids):
                row = id_to_row[rid]
                new_cos_map[rid] = float(np.dot(img_emb[row], txt_emb[j]))
        except Exception as e:
            logger.warning(f"  batch {bs} 실패: {e}")

    # 8) 비교 분석
    deltas = []
    for rid in food_ids:
        if rid in new_cos_map and rid in old_cos:
            d = new_cos_map[rid] - old_cos[rid]
            deltas.append({"id": rid, "old": old_cos[rid],
                           "new": new_cos_map[rid], "delta": d})
    n_better = sum(1 for d in deltas if d["delta"] > 0)
    n_worse = sum(1 for d in deltas if d["delta"] <= 0)
    avg = sum(d["delta"] for d in deltas) / max(len(deltas), 1)

    logger.info(f"\n  비교: 개선 {n_better}/{len(deltas)}, 악화 {n_worse}/{len(deltas)}")
    logger.info(f"  평균 Δ: {avg:+.4f}")

    # 9) 결과 저장
    summary = {
        "category": "food",
        "n_targets": len(food_ids),
        "n_recaptioned": len(new_cos_map),
        "n_improved": n_better,
        "n_regressed": n_worse,
        "avg_delta": round(avg, 4),
        "captions": done,
        "comparison": deltas,
    }
    OUT_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    md = ["# food 카테고리 재캡션 v2 — 결과\n",
          f"실행: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
          f"모델: Qwen2.5-VL-3B-Instruct (동일)\n\n",
          "## 통계\n\n",
          f"- 대상: **{len(food_ids)}건**\n",
          f"- 재캡션 성공: {len(new_cos_map)}건\n",
          f"- 개선: **{n_better}/{len(deltas)}** ({n_better/max(len(deltas),1)*100:.1f}%)\n",
          f"- 악화: {n_worse}/{len(deltas)}\n",
          f"- 평균 Δ cosine: **{avg:+.4f}**\n\n"]

    deltas_sorted = sorted(deltas, key=lambda x: -x["delta"])
    md.append("## Top 10 개선 사례\n\n")
    md.append("| ID | old | new | Δ |\n|---|---|---|---|\n")
    for d in deltas_sorted[:10]:
        md.append(f"| `{d['id'][:40]}` | {d['old']:.4f} | {d['new']:.4f} | "
                  f"{d['delta']:+.4f} |\n")

    md.append("\n## 결론\n\n")
    if avg > 0.05:
        md.append("**유의미한 개선** — 다른 카테고리(cat/nature) 도 진행 권장.\n")
    elif avg > 0.01:
        md.append("**부분 개선** — 효과 검토 후 결정.\n")
    else:
        md.append("**개선 미미** — 모델/데이터 한계.\n")

    md_path = SCRIPTS_DIR / "caption_food_v2.md"
    md_path.write_text("".join(md), encoding="utf-8")

    logger.info(f"\n  → {OUT_PATH}")
    logger.info(f"  → {md_path}")
    logger.info(f"\n완료 — 소요 {(time.time() - t0)/60:.1f}분")


if __name__ == "__main__":
    main()
