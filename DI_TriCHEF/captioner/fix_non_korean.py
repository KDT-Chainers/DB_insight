"""DI_TriCHEF/captioner/fix_non_korean.py — 비한국어 캡션 선별 재생성.

재캡션 완료 후 `<stem>.txt` 를 스캔하여 다음에 해당하는 파일만 재생성:
  · 한자(CJK Unified) 30% 이상 포함
  · 한글(Hangul) 30% 미만
  · 빈 파일 또는 "(ERROR" 로 시작

재생성 시에는 더 강한 프롬프트를 사용하고, 그래도 한자가 남으면
한자 제거 후 저장 (lossy fallback).

실행:
    python DI_TriCHEF/captioner/fix_non_korean.py              # dry-run (대상만 집계)
    python DI_TriCHEF/captioner/fix_non_korean.py --apply      # 실제 재생성
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "App" / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from captioner.qwen_vl_ko import QwenKoCaptioner  # noqa: E402

EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
HANJA_RE  = re.compile(r"[\u4e00-\u9fff]")  # CJK Unified Ideographs

STRONG_PROMPT = (
    "이미지를 보고 한국어 한글만 사용하여 한 문장(40자 이내)으로 설명하세요. "
    "한자(漢字), 중국어, 영어는 절대 쓰지 마세요. "
    "예시 스타일: '해변에서 사람들이 걷고 있다', '차량 내부 디스플레이가 보인다'."
)


def _lang_stats(s: str) -> tuple[int, int, int]:
    hangul = len(HANGUL_RE.findall(s))
    hanja  = len(HANJA_RE.findall(s))
    total  = len(s)
    return hangul, hanja, total


def _needs_fix(text: str) -> tuple[bool, str]:
    t = text.strip()
    if not t:
        return True, "empty"
    if t.startswith("(ERROR") or t.startswith("(캡션"):
        return True, "error"
    hangul, hanja, total = _lang_stats(t)
    if total < 4:
        return True, "too_short"
    if hanja >= 3 and hangul / max(total, 1) < 0.3:
        return True, f"chinese(hj={hanja},han={hangul},n={total})"
    if hangul / max(total, 1) < 0.3:
        return True, f"low_hangul({hangul}/{total})"
    return False, "ok"


def _find_img_for_stem(img_root: Path, stem: str) -> Path | None:
    for ext in EXTS:
        for p in img_root.rglob(f"{stem}{ext}"):
            return p
        for p in img_root.rglob(f"{stem}{ext.upper()}"):
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 재생성 (기본 dry-run)")
    args = ap.parse_args()

    try:
        from config import PATHS
        cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
        img_root = Path(PATHS["RAW_DB"]) / "Img"
    except Exception:
        cap_dir  = ROOT / "Data" / "extracted_DB" / "Img" / "captions"
        img_root = ROOT / "Data" / "raw_DB" / "Img"

    txt_files = sorted(cap_dir.glob("*.txt"))
    print(f"[fix] scan {len(txt_files)} .txt files …")
    targets: list[tuple[Path, str]] = []
    for tp in txt_files:
        text = tp.read_text(encoding="utf-8", errors="ignore")
        bad, reason = _needs_fix(text)
        if bad:
            targets.append((tp, reason))

    print(f"[fix] 재생성 대상: {len(targets)}장")
    for tp, reason in targets[:20]:
        print(f"  - {tp.name:40s} [{reason}]")
    if len(targets) > 20:
        print(f"  … 외 {len(targets)-20}장")

    if not args.apply or not targets:
        print("[fix] dry-run 종료 (실제 적용은 --apply 필요)")
        return 0

    try:
        from PIL import Image
    except ImportError:
        print("[fix] Pillow 필요"); return 2

    cap = QwenKoCaptioner(dtype="float16")
    t0 = time.time()
    fixed = 0
    skipped = 0
    for i, (tp, reason) in enumerate(targets, 1):
        stem = tp.stem
        img = _find_img_for_stem(img_root, stem)
        if img is None:
            print(f"[{i}/{len(targets)}] {stem}: 이미지 없음 → skip")
            skipped += 1
            continue
        try:
            im = Image.open(img).convert("RGB")
            text = cap.caption(im, prompt=STRONG_PROMPT,
                               max_new_tokens=60, max_image_side=896)
        except Exception as e:
            text = f"(ERROR: {type(e).__name__})"

        # 한자 제거 lossy fallback
        if HANJA_RE.search(text):
            cleaned = HANJA_RE.sub("", text).strip()
            if len(cleaned) >= 4:
                text = cleaned

        tp.write_text(text, encoding="utf-8")
        fixed += 1
        if i % 10 == 0 or i == len(targets):
            print(f"[{i}/{len(targets)}] fixed={fixed} skipped={skipped} "
                  f"elapsed={time.time()-t0:.1f}s")
            print(f"   └─ {tp.name}: {text[:80]}")

    print(f"\n[fix] 완료 fixed={fixed} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
