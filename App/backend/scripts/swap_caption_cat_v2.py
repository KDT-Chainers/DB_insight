"""scripts/swap_caption_cat_v2.py — caption_cat_v2 결과를 caption_3stage.json 에 swap.

  1. caption_3stage.json 자동 백업 → caption_3stage.bak_<timestamp>.json
  2. cat 재캡션 결과(caption_cat_v2_ckpt.json) 의 ID 만 부분 갱신
  3. SigLIP2 cosine 임베딩 캐시 도 갱신 필요 → 별도 단계 (rebuild_img_caption_embed.py)

⚠️ 사용자 명시 승인 후에만 실행. --dry-run 옵션 권장.

사용:
  python scripts/swap_caption_cat_v2.py --dry-run     # 변경 미리보기
  python scripts/swap_caption_cat_v2.py               # 실제 적용 (백업 포함)
  python scripts/swap_caption_cat_v2.py --rollback    # 직전 백업으로 복원
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

CAPTION_PATH = None  # config 에서 로드


def _ensure_caption_path() -> Path:
    global CAPTION_PATH
    if CAPTION_PATH is None:
        from config import PATHS
        CAPTION_PATH = Path(PATHS["TRICHEF_IMG_CACHE"]) / "caption_3stage.json"
    return CAPTION_PATH


def latest_backup() -> Path | None:
    cap_path = _ensure_caption_path()
    backups = sorted(cap_path.parent.glob("caption_3stage.bak_*.json"))
    return backups[-1] if backups else None


def cmd_swap(dry_run: bool):
    cap_path = _ensure_caption_path()
    cat_ckpt = SCRIPTS_DIR / "caption_cat_v2_ckpt.json"

    if not cap_path.exists():
        logger.error(f"원본 없음: {cap_path}")
        return 2
    if not cat_ckpt.exists():
        logger.error(f"cat 재캡션 결과 없음: {cat_ckpt}")
        return 2

    cap = json.loads(cap_path.read_text(encoding="utf-8"))
    cat = json.loads(cat_ckpt.read_text(encoding="utf-8"))

    # 원본 구조: {"ids": [...], "L1": [...], "L2": [...], "L3": [...]} 평행 리스트
    ids = cap.get("ids", [])
    L1 = cap.get("L1", [])
    L2 = cap.get("L2", [])
    L3 = cap.get("L3", [])
    id_to_idx = {_id: i for i, _id in enumerate(ids)}

    n_targets = 0
    n_swapped = 0
    n_missing_in_orig = 0
    n_missing_caption = 0
    sample_changes = []

    for rid, entry in cat.items():
        if not isinstance(entry, dict) or entry.get("error"):
            continue
        n_targets += 1
        parts = entry.get("parts") or {}
        title = parts.get("title", "")
        tagline = parts.get("tagline", "")
        synopsis = parts.get("synopsis", "")
        tags_kr = parts.get("tags_kr", "")
        tags_en = parts.get("tags_en", "")
        if not title and not synopsis:
            n_missing_caption += 1
            continue

        idx = id_to_idx.get(rid)
        if idx is None:
            n_missing_in_orig += 1
            continue

        new_l1 = title
        new_l2 = (tagline + " " + tags_kr).strip()
        new_l3 = (synopsis + " " + tags_en).strip()

        if len(sample_changes) < 5:
            sample_changes.append({
                "id": rid,
                "old_l1": L1[idx] if idx < len(L1) else "",
                "new_l1": new_l1,
            })

        # 길이 맞추기
        while idx >= len(L1): L1.append("")
        while idx >= len(L2): L2.append("")
        while idx >= len(L3): L3.append("")

        if not dry_run:
            L1[idx] = new_l1
            L2[idx] = new_l2
            L3[idx] = new_l3
        n_swapped += 1

    logger.info(f"  대상: {n_targets}건")
    logger.info(f"  swap: {n_swapped}건")
    logger.info(f"  원본 ID 누락: {n_missing_in_orig}건")
    logger.info(f"  캡션 누락: {n_missing_caption}건")

    logger.info("\n  Sample 변경 (top 5):")
    for s in sample_changes:
        logger.info(f"    [{s['id'][:50]}]")
        logger.info(f"      OLD: {s['old_l1'][:80]}")
        logger.info(f"      NEW: {s['new_l1'][:80]}")

    if dry_run:
        logger.info("\n  ⚠️ DRY RUN — 변경 미적용. --dry-run 제외하고 재실행 시 swap.")
        return 0

    if n_swapped == 0:
        logger.error("\n  swap 대상 0건 — 적용 중단.")
        return 2

    # 백업
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = cap_path.parent / f"caption_3stage.bak_{ts}.json"
    shutil.copy2(cap_path, backup_path)
    logger.info(f"\n  백업: {backup_path}")

    # 저장
    cap["ids"] = ids
    cap["L1"] = L1
    cap["L2"] = L2
    cap["L3"] = L3
    cap_path.write_text(json.dumps(cap, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"  저장: {cap_path}")
    logger.info(f"\n✓ {n_swapped}건 swap 완료. 검색 효과 확인을 위해 cache_img_Im_*.npy 재생성 필요.")
    return 0


def cmd_rollback():
    cap_path = _ensure_caption_path()
    bk = latest_backup()
    if not bk:
        logger.error("백업 없음 — rollback 불가.")
        return 2
    logger.info(f"  복원 대상: {bk}")
    shutil.copy2(bk, cap_path)
    logger.info(f"  복원 완료: {cap_path}")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="변경 미리보기 (적용 안함)")
    parser.add_argument("--rollback", action="store_true", help="직전 백업으로 복원")
    args = parser.parse_args()

    if args.rollback:
        sys.exit(cmd_rollback())
    sys.exit(cmd_swap(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
