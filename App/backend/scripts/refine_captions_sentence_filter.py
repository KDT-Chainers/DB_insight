"""[Phase C 후속] 캡션 문장 단위 한국어 필터 — 혼합 언어 캡션 정제.

배경:
  Phase C 가드레일은 stage 단위로 작동 — 한 stage에서 한국어 비율이 낮으면 폐기.
  그러나 실제 Qwen2-VL 응답은 한국어 문장 + 중국어 문장이 혼합된 경우 다수:

  예: "'화려한 꽃과 매달린 벚꽃잎들이 조명 아래 박차락하게 움직입니다.'
       - 主要物体：装饰性的白色花束和悬挂的花生壳。
       - 角色无明确存在..."

  → 첫 문장은 유효한 한국어. 가드레일이 통째로 폐기하면 정보 손실.

해법:
  - captions_triple.jsonl 를 순회
  - 각 stage 텍스트를 문장 단위로 분리 (`\n`, `.`, `。` 기준)
  - 문장별 한국어 비율 ≥ 10% 이면 유지, 그 외 폐기
  - 정제된 캡션을 새 jsonl 로 출력 (원본은 보존)

후속 통합:
  - 정제된 jsonl 을 검색 인덱스 재구축에 사용
  - 또는 임베딩 재생성 (text_emb 만 다시) — Re/Z 시각축은 유지

사용:
  python refine_captions_sentence_filter.py            # 전체 재정제
  python refine_captions_sentence_filter.py --dry-run  # 미리보기
  python refine_captions_sentence_filter.py --limit 50 # 처음 50건만
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "App" / "backend"))
from config import PATHS  # noqa: E402

CAPTIONS = Path(PATHS["TRICHEF_IMG_CACHE"]) / "captions_triple.jsonl"


# 문장 분리 — 한국어/영어/중국어 모두 호환
_SENT_SPLIT = re.compile(r"[。.!?！？\n]+")


def _ko_ratio(s: str) -> float:
    if not s:
        return 0.0
    return sum(1 for c in s if '가' <= c <= '힣') / len(s)


def _zh_ratio(s: str) -> float:
    if not s:
        return 0.0
    return sum(1 for c in s if '一' <= c <= '鿿') / len(s)


def _refine_text(text: str, min_ko: float = 0.10, max_zh: float = 0.15) -> str:
    """문장 단위로 분리해 한국어 비율 충족하는 문장만 보존."""
    if not text:
        return ""
    parts = _SENT_SPLIT.split(text)
    kept = []
    for p in parts:
        p = p.strip(" '\"-•")
        if len(p) < 4:
            continue
        # 한국어 문장만 통과 (혼합 문장은 중국어 비율로 결정)
        if _zh_ratio(p) > max_zh:
            continue
        if _ko_ratio(p) >= min_ko or len(p) > 20 and _ko_ratio(p) >= 0.05:
            kept.append(p)
    return "\n".join(kept).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-ko", type=float, default=0.10)
    ap.add_argument("--max-zh", type=float, default=0.15)
    args = ap.parse_args()

    if not CAPTIONS.exists():
        print(f"[error] {CAPTIONS} 없음")
        sys.exit(1)

    src_lines = []
    with CAPTIONS.open("r", encoding="utf-8") as f:
        for ln in f:
            src_lines.append(ln)

    if args.limit > 0:
        src_lines = src_lines[:args.limit]
    print(f"=== 캡션 정제: {len(src_lines)}건 ===")

    out_path = CAPTIONS.with_suffix(".refined.jsonl")
    stats = {"total": 0, "refined": 0, "unchanged": 0, "emptied": 0}
    changes_sample = []

    new_lines = []
    for ln in src_lines:
        try:
            d = json.loads(ln)
        except Exception:
            new_lines.append(ln)
            continue
        stats["total"] += 1
        any_changed = False
        any_remaining = False
        for st in ["title", "tagline", "synopsis", "tags_kr"]:
            orig = d.get(st, "") or ""
            new = _refine_text(orig, min_ko=args.min_ko, max_zh=args.max_zh)
            if new != orig:
                any_changed = True
                d[st] = new
            if new:
                any_remaining = True
        # tags_en 은 영어 전용 — 정제 제외
        # L1/L2/L3 재합성
        d["L1"] = d.get("title", "")
        d["L2"] = (d.get("tagline", "") + " " + d.get("tags_kr", "")).strip()
        d["L3"] = (d.get("synopsis", "") + " " + d.get("tags_en", "")).strip()
        if any_changed:
            stats["refined"] += 1
            if len(changes_sample) < 5:
                changes_sample.append((d.get("key", "?")[:50], d.get("L3", "")[:120]))
        else:
            stats["unchanged"] += 1
        if any_changed and not any_remaining:
            stats["emptied"] += 1
        new_lines.append(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"  정제됨: {stats['refined']}")
    print(f"  변경 없음: {stats['unchanged']}")
    print(f"  모두 비워짐(완전 폐기): {stats['emptied']}")
    print(f"\n샘플 변경 (after refine):")
    for k, t in changes_sample:
        print(f"  {k}: {t!r}")

    if args.dry_run:
        print(f"\n[dry-run] 출력 미저장 ({out_path})")
        return

    out_path.write_text("".join(new_lines), encoding="utf-8")
    print(f"\n✓ 저장: {out_path}")
    print("  원본 보존: captions_triple.jsonl")
    print("  적용 시: cp captions_triple.refined.jsonl captions_triple.jsonl 후 임베딩 재생성")


if __name__ == "__main__":
    main()
