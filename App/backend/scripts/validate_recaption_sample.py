"""scripts/validate_recaption_sample.py — 10건 샘플 재캡션 검증.

목적: Qwen2.5-VL-3B 재실행 시 같은 이미지의 캡션 cosine 이 개선되는지 확인.

  1. real_caption_lies.json 에서 cosine 가장 낮은 10건 선택
  2. 동일 모델(Qwen2.5-VL-3B)로 재캡션 (5-stage 모두)
  3. SigLIP2 image-text cosine 재측정
  4. 기존 vs 신규 비교

산출물: scripts/recaption_validation.json + .md

⚠️ caption_3stage.json 원본 변경 없음 — 측정만.
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

N_SAMPLES = 10

PROMPTS = {
    "title":
        "이 사진의 핵심을 1줄로 한국어로 표현하세요. 객체와 핵심 행동만 간결하게.",
    "tagline":
        "이 사진의 분위기, 감정, 시각적 인상을 한국어로 1~2문장으로 묘사하세요.",
    "synopsis":
        "이 사진을 한국어로 자세히 묘사하세요. 주요 객체, 인물 유무, 행동, 위치, 색감, 분위기를 3~5문장으로.",
    "tags_kr":
        "이 사진을 표현하는 한국어 키워드를 10~20개 쉼표로 구분하여 출력하세요.",
    "tags_en":
        "Output 10~20 English keywords separated by commas describing this image.",
}
MAX_NEW_TOKENS = {"title": 30, "tagline": 60, "synopsis": 150, "tags_kr": 80, "tags_en": 80}


def main():
    logger.info("═" * 60)
    logger.info(f"재캡션 검증 — 샘플 {N_SAMPLES}건")
    logger.info("═" * 60)
    t0 = time.time()

    # 1) 최악 cosine 10건 선택
    lies_path = SCRIPTS_DIR / "real_caption_lies.json"
    if not lies_path.exists():
        logger.error(f"{lies_path} 없음 — run_next_improvement_pipeline.py 먼저 실행")
        return
    lies = json.loads(lies_path.read_text(encoding="utf-8"))
    items = sorted(lies.get("real_lies", []), key=lambda x: x.get("cosine", 0))[:N_SAMPLES]
    logger.info(f"  선택 {len(items)}건 (cosine 범위 {items[0]['cosine']:.3f} ~ {items[-1]['cosine']:.3f})")

    # 2) 이미지 경로 + 기존 cosine 캡처
    from config import PATHS
    raw_img_dir = Path(PATHS["RAW_DB"]) / "Img"
    cache_dir = Path(PATHS["TRICHEF_IMG_CACHE"])

    samples = []
    for it in items:
        rid = it["id"]
        img_path = raw_img_dir / rid
        if not img_path.exists():
            logger.warning(f"  이미지 없음: {img_path}")
            continue
        samples.append({
            "id": rid,
            "img_path": str(img_path),
            "old_caption": it.get("caption", ""),
            "old_cosine": float(it["cosine"]),
        })
    logger.info(f"  검증 가능: {len(samples)}건")

    # 3) Qwen 모델 로드
    logger.info("\n  Qwen2.5-VL-3B 로드 중...")
    from captioner.qwen_vl_ko import QwenKoCaptioner
    cap = QwenKoCaptioner(dtype="float16")
    cap._load()
    logger.info("  로드 완료")

    # 4) 각 stage 별 batch 재캡션 (GPU 병렬 활용)
    logger.info("\n  재캡션 진행 중 (batch parallel)...")
    img_paths = [s["img_path"] for s in samples]
    for s in samples:
        s["new_parts"] = {}
    for stage, prompt in PROMPTS.items():
        t_stage = time.time()
        try:
            results = cap.caption_batch(img_paths, prompt=prompt,
                                          max_new_tokens=MAX_NEW_TOKENS[stage])
            for s, txt in zip(samples, results):
                s["new_parts"][stage] = (txt or "").strip()
            logger.info(f"  [{stage}] {len(samples)}건 / {time.time() - t_stage:.1f}s")
        except Exception as e:
            logger.warning(f"  [{stage}] batch 실패 — 단건 fallback: {e}")
            for i, s in enumerate(samples):
                try:
                    txt = cap.caption(s["img_path"], prompt=prompt,
                                       max_new_tokens=MAX_NEW_TOKENS[stage])
                    s["new_parts"][stage] = (txt or "").strip()
                except Exception as e2:
                    logger.warning(f"    [{i}] 실패: {e2}")
                    s["new_parts"][stage] = ""

    for s in samples:
        np_ = s["new_parts"]
        l1 = np_.get("title", "")
        l2 = (np_.get("tagline", "") + " " + np_.get("tags_kr", "")).strip()
        l3 = (np_.get("synopsis", "") + " " + np_.get("tags_en", "")).strip()
        s["new_caption"] = (l1 + " " + l2 + " " + l3).strip()
        logger.info(f"  {s['id'][:50]} → {l1[:60]}")

    # 5) SigLIP2 cosine 재측정
    logger.info("\n  SigLIP2 cosine 재측정...")
    import numpy as np
    from embedders.trichef import siglip2_re

    img_emb_all = np.load(str(cache_dir / "cache_img_Re_siglip2.npy"))
    norms = np.linalg.norm(img_emb_all, axis=1, keepdims=True)
    img_emb_all = (img_emb_all / np.maximum(norms, 1e-8)).astype(np.float32, copy=False)
    ids_data = json.loads((cache_dir / "img_ids.json").read_text(encoding="utf-8"))
    ids = ids_data.get("ids") if isinstance(ids_data, dict) else ids_data
    id_to_row = {_id: i for i, _id in enumerate(ids)}

    captions_new = [s["new_caption"] for s in samples]
    txt_emb = siglip2_re.embed_texts(captions_new)
    txt_emb = np.asarray(txt_emb, dtype=np.float32)
    norms2 = np.linalg.norm(txt_emb, axis=1, keepdims=True)
    txt_emb = txt_emb / np.maximum(norms2, 1e-8)

    for i, s in enumerate(samples):
        row = id_to_row.get(s["id"])
        if row is None:
            s["new_cosine"] = None
            continue
        img_vec = img_emb_all[row]
        s["new_cosine"] = float(np.dot(img_vec, txt_emb[i]))

    # 6) 결과 분석
    improvements = []
    regressions = []
    for s in samples:
        if s.get("new_cosine") is None:
            continue
        delta = s["new_cosine"] - s["old_cosine"]
        s["delta"] = delta
        if delta > 0:
            improvements.append(delta)
        else:
            regressions.append(delta)

    n_better = sum(1 for s in samples if (s.get("delta") or 0) > 0)
    n_worse = sum(1 for s in samples if (s.get("delta") or 0) <= 0)
    avg_delta = sum(s.get("delta") or 0 for s in samples) / max(len(samples), 1)

    logger.info("\n  결과:")
    logger.info(f"    개선: {n_better}/{len(samples)}")
    logger.info(f"    악화: {n_worse}/{len(samples)}")
    logger.info(f"    평균 Δ: {avg_delta:+.4f}")

    out = {
        "n_samples": len(samples),
        "improvements": n_better,
        "regressions": n_worse,
        "avg_delta": round(avg_delta, 4),
        "samples": samples,
    }
    (SCRIPTS_DIR / "recaption_validation.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    md = ["# 재캡션 검증 — 10건 샘플\n",
          f"실행: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
          f"모델: Qwen2.5-VL-3B-Instruct (동일 모델)\n\n",
          f"## 결과\n\n",
          f"- 개선: **{n_better}/{len(samples)}**\n",
          f"- 악화: {n_worse}/{len(samples)}\n",
          f"- 평균 Δ cosine: **{avg_delta:+.4f}**\n\n",
          "## 샘플별 비교\n\n",
          "| ID | 기존 cos | 신규 cos | Δ | 신규 title |\n",
          "|---|---|---|---|---|\n"]
    for s in samples:
        nc = s.get("new_cosine")
        d = s.get("delta")
        title = (s.get("new_parts") or {}).get("title", "")[:50]
        nc_s = f"{nc:.4f}" if nc is not None else "-"
        d_s = f"{d:+.4f}" if d is not None else "-"
        md.append(f"| `{s['id'][:35]}` | {s['old_cosine']:.4f} | {nc_s} | {d_s} | {title} |\n")

    md.append("\n## 결론\n\n")
    if avg_delta > 0.05:
        md.append(f"**유의미한 개선** (평균 Δ {avg_delta:+.4f}) — 대규모 재캡션 가치 입증.\n")
    elif avg_delta > 0.01:
        md.append(f"**부분 개선** (평균 Δ {avg_delta:+.4f}) — 신중한 적용.\n")
    else:
        md.append(f"**개선 미미** (평균 Δ {avg_delta:+.4f}) — 모델 한계, 다른 방향 필요.\n")

    (SCRIPTS_DIR / "recaption_validation.md").write_text("".join(md), encoding="utf-8")
    logger.info(f"\n  → scripts/recaption_validation.json")
    logger.info(f"  → scripts/recaption_validation.md")
    logger.info(f"\n완료 — 소요 {(time.time() - t0)/60:.1f}분")


if __name__ == "__main__":
    main()
