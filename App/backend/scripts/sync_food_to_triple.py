"""scripts/sync_food_to_triple.py — food v2 캡션을 captions_triple.jsonl 에 동기화.

caption_3stage.json 만으로는 검색에 효과 없음. captions_triple.jsonl 도 업데이트
필요 (cache_img_Im_L1/L2/L3.npy 의 입력 소스).

  1. captions_triple.jsonl 자동 백업
  2. food v2 결과(caption_food_v2_ckpt.json)의 ID 만 in-place 갱신
  3. (별도) rebuild_im_cache_all.py --img-only 로 BGE-M3 재임베딩

사용:
  python scripts/sync_food_to_triple.py --dry-run
  python scripts/sync_food_to_triple.py
  python scripts/sync_food_to_triple.py --rollback
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = _BACKEND_DIR / "scripts"
sys.path.insert(0, str(_BACKEND_DIR))


def _jsonl_path() -> Path:
    from config import PATHS
    return Path(PATHS["TRICHEF_IMG_CACHE"]) / "captions_triple.jsonl"


def latest_backup() -> Path | None:
    p = _jsonl_path()
    backups = sorted(p.parent.glob("captions_triple.bak_*.jsonl"))
    return backups[-1] if backups else None


def cmd_sync(dry_run: bool):
    jsonl = _jsonl_path()
    food_ckpt = SCRIPTS_DIR / "caption_food_v2_ckpt.json"

    if not jsonl.exists():
        logger.error(f"원본 없음: {jsonl}")
        return 2
    if not food_ckpt.exists():
        logger.error(f"food 재캡션 결과 없음: {food_ckpt}")
        return 2

    food = json.loads(food_ckpt.read_text(encoding="utf-8"))

    # food: {id: {parts: {title, tagline, synopsis, tags_kr, tags_en}, caption: ...}}
    food_map = {}
    for rid, entry in food.items():
        if not isinstance(entry, dict) or entry.get("error"):
            continue
        parts = entry.get("parts") or {}
        if not parts.get("title") and not parts.get("synopsis"):
            continue
        food_map[rid] = parts

    logger.info(f"  food v2 갱신 가능: {len(food_map)}건")

    # captions_triple.jsonl 읽기 (line by line)
    new_lines = []
    n_swapped = 0
    sample_changes = []
    with jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                new_lines.append(line)
                continue
            key = obj.get("key")
            if key in food_map:
                parts = food_map[key]
                title = parts.get("title", "")
                tagline = parts.get("tagline", "")
                synopsis = parts.get("synopsis", "")
                tags_kr = parts.get("tags_kr", "")
                tags_en = parts.get("tags_en", "")
                new_obj = dict(obj)  # copy
                # rebuild_im_cache_all.py:35-50 가 읽는 키 동일 갱신
                new_obj["L1"] = title
                new_obj["L2"] = (tagline + " " + tags_kr).strip()
                new_obj["L3"] = (synopsis + " " + tags_en).strip()
                new_obj["title"] = title
                new_obj["tagline"] = tagline
                new_obj["synopsis"] = synopsis
                new_obj["tags_kr"] = tags_kr
                new_obj["tags_en"] = tags_en
                if len(sample_changes) < 5:
                    sample_changes.append({
                        "key": key,
                        "old_l1": obj.get("L1", ""),
                        "new_l1": new_obj["L1"],
                    })
                new_lines.append(json.dumps(new_obj, ensure_ascii=False))
                n_swapped += 1
            else:
                new_lines.append(line)

    logger.info(f"  swap: {n_swapped}/{len(food_map)}건")

    logger.info("\n  Sample 변경 (top 5):")
    for s in sample_changes:
        logger.info(f"    [{s['key'][:40]}]")
        logger.info(f"      OLD L1: {s['old_l1'][:80]}")
        logger.info(f"      NEW L1: {s['new_l1'][:80]}")

    if dry_run:
        logger.info("\n  ⚠️ DRY RUN — 변경 미적용")
        return 0

    if n_swapped == 0:
        logger.error("  swap 0건 — 중단")
        return 2

    # 백업
    ts = time.strftime("%Y%m%d_%H%M%S")
    bk = jsonl.parent / f"captions_triple.bak_{ts}.jsonl"
    shutil.copy2(jsonl, bk)
    logger.info(f"  백업: {bk}")

    # 저장
    jsonl.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    logger.info(f"  저장: {jsonl}")
    logger.info(f"\n✓ {n_swapped}건 sync 완료. cache_img_Im_*.npy 재생성 필요:")
    logger.info("   cd App/backend && python scripts/rebuild_im_cache_all.py --img-only")
    return 0


def cmd_rollback():
    jsonl = _jsonl_path()
    bk = latest_backup()
    if not bk:
        logger.error("백업 없음")
        return 2
    shutil.copy2(bk, jsonl)
    logger.info(f"  복원: {bk} → {jsonl}")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if args.rollback:
        sys.exit(cmd_rollback())
    sys.exit(cmd_sync(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
