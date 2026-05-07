"""merge_img_stage_captions.py — Qwen2.5-VL-3B stage 파일 → captions_triple.jsonl 병합.

rebuild_img_qwen_full_caption.py 가 생성하는 파일:
  extracted_DB/Img/captions/{key}_title.txt
  extracted_DB/Img/captions/{key}_tagline.txt
  extracted_DB/Img/captions/{key}_synopsis.txt
  extracted_DB/Img/captions/{key}_tags_kr.txt
  extracted_DB/Img/captions/{key}_tags_en.txt

매핑:
  L1 = title (짧은 한줄)
  L2 = tagline + tags_kr (키워드)
  L3 = synopsis (상세 설명)
  tags_en → cross-lingual 검색을 위해 L3에 append

결과:
  Data/embedded_DB/Img/captions_triple.jsonl (덮어쓰기 또는 업데이트)
  기존 항목 중 새 stage 파일 없는 것은 원본 유지 (partial merge)
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT        = Path(__file__).resolve().parents[3]
IMG_CACHE   = ROOT / "Data" / "embedded_DB" / "Img"
IMG_CAP_DIR = ROOT / "Data" / "extracted_DB" / "Img" / "captions"
JSONL_PATH  = IMG_CACHE / "captions_triple.jsonl"
IDS_PATH    = IMG_CACHE / "img_ids.json"

STAGES = ["title", "tagline", "synopsis", "tags_kr", "tags_en"]


def _read_stage(cap_dir: Path, key: str, stage: str) -> str:
    """key_stage.txt 읽기. 없으면 빈 문자열."""
    safe_key = key.replace("/", "__").replace("\\", "__")
    fp = cap_dir / f"{safe_key}_{stage}.txt"
    if fp.exists():
        try:
            return fp.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            return ""
    return ""


def _has_any_stage(cap_dir: Path, key: str) -> bool:
    """하나라도 stage 파일이 있으면 True."""
    safe_key = key.replace("/", "__").replace("\\", "__")
    for s in STAGES:
        if (cap_dir / f"{safe_key}_{s}.txt").exists():
            return True
    return False


def main():
    t0 = time.time()
    print(f"[merge] Image stage 캡션 병합 시작", flush=True)
    print(f"  CAP_DIR: {IMG_CAP_DIR}", flush=True)
    print(f"  JSONL: {JSONL_PATH}", flush=True)

    # 기존 captions_triple.jsonl 로드
    existing: dict[str, dict] = {}
    if JSONL_PATH.exists():
        with JSONL_PATH.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    key = d.get("key") or d.get("id", "")
                    if key:
                        existing[key] = d
                except Exception:
                    continue
        print(f"  기존 JSONL: {len(existing)}건", flush=True)

    # img_ids.json 로드
    ids_raw = json.loads(IDS_PATH.read_text(encoding="utf-8"))
    ids = ids_raw.get("ids", ids_raw) if isinstance(ids_raw, dict) else ids_raw
    print(f"  img_ids: {len(ids)}건", flush=True)

    updated = skipped = new_added = 0

    out_lines: list[str] = []

    for key in ids:
        if not _has_any_stage(IMG_CAP_DIR, key):
            # 새 stage 파일 없음 → 기존 항목 유지
            entry = existing.get(key, {"key": key, "L1": "", "L2": "", "L3": ""})
            out_lines.append(json.dumps(entry, ensure_ascii=False))
            skipped += 1
            continue

        # stage 파일 읽기
        title    = _read_stage(IMG_CAP_DIR, key, "title")
        tagline  = _read_stage(IMG_CAP_DIR, key, "tagline")
        synopsis = _read_stage(IMG_CAP_DIR, key, "synopsis")
        tags_kr  = _read_stage(IMG_CAP_DIR, key, "tags_kr")
        tags_en  = _read_stage(IMG_CAP_DIR, key, "tags_en")

        # L1 = title
        L1 = title or (existing.get(key, {}).get("L1", ""))

        # L2 = tagline + 태그 한국어 (키워드 레이어)
        l2_parts = [tagline, tags_kr]
        L2 = " | ".join(p for p in l2_parts if p) or existing.get(key, {}).get("L2", "")

        # L3 = synopsis + 영어 태그 (cross-lingual 레이어)
        l3_parts = [synopsis]
        if tags_en:
            l3_parts.append(f"[EN] {tags_en}")
        L3 = " ".join(p for p in l3_parts if p) or existing.get(key, {}).get("L3", "")

        entry = {
            "key": key,
            "L1": L1,
            "L2": L2,
            "L3": L3,
            # 원본 필드 보존
            "title": title,
            "tagline": tagline,
            "synopsis": synopsis,
            "tags_kr": tags_kr,
            "tags_en": tags_en,
        }
        out_lines.append(json.dumps(entry, ensure_ascii=False))
        if key in existing:
            updated += 1
        else:
            new_added += 1

    # 백업 후 덮어쓰기
    if JSONL_PATH.exists():
        bak = JSONL_PATH.with_suffix(".jsonl.bak")
        bak.write_bytes(JSONL_PATH.read_bytes())
        print(f"  백업: {bak}", flush=True)

    JSONL_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    elapsed = time.time() - t0
    print(f"\n[merge] 완료 — 업데이트:{updated} 신규:{new_added} 유지:{skipped} ({elapsed:.1f}s)")
    print(f"  JSONL 저장: {JSONL_PATH} ({len(out_lines)}건)")


if __name__ == "__main__":
    main()
