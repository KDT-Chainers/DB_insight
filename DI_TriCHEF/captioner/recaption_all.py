"""DI_TriCHEF/captioner/recaption_all.py — Qwen KR 전체 재캡션 배치.

모든 raw_DB/Img 하위 이미지를 Qwen2-VL-2B 로 재캡션하여
extracted_DB/Img/captions/<stem>.txt 에 덮어씀.

특징:
  · 재개 가능: <stem>.qwen 마커 파일로 완료 추적
  · 진행률 + ETA + 실패 로그
  · Ctrl+C 시 안전 종료 (현재 이미지 완료 후 stop)
  · --limit N 옵션: 테스트용

실행:
    cd DB_insight
    python DI_TriCHEF/captioner/recaption_all.py
    python DI_TriCHEF/captioner/recaption_all.py --limit 50       # 테스트
    python DI_TriCHEF/captioner/recaption_all.py --force          # 마커 무시 전체 재실행
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "App" / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from captioner.qwen_vl_ko import QwenKoCaptioner  # noqa: E402

EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tiff", ".heic", ".heif", ".avif"}

_STOP = False
def _handle_sigint(signum, frame):
    global _STOP
    _STOP = True
    print("\n[recaption] Ctrl+C 감지 — 현재 이미지 완료 후 종료합니다.")

signal.signal(signal.SIGINT, _handle_sigint)


def _resolve_caption_dir() -> Path:
    try:
        from config import PATHS
        return Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    except Exception:
        return ROOT / "Data" / "extracted_DB" / "Img" / "captions"


def _resolve_img_root() -> Path:
    try:
        from config import PATHS
        return Path(PATHS["RAW_DB"]) / "Img"
    except Exception:
        return ROOT / "Data" / "raw_DB" / "Img"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="N장만 처리 (0=전체)")
    ap.add_argument("--force", action="store_true", help="마커 무시 전체 재실행")
    ap.add_argument("--dtype", default="float16",
                    choices=["bfloat16", "float16", "float32"])
    ap.add_argument("--max-side", type=int, default=896)
    ap.add_argument("--max-tokens", type=int, default=60)
    args = ap.parse_args()

    img_root = _resolve_img_root()
    cap_dir = _resolve_caption_dir()
    cap_dir.mkdir(parents=True, exist_ok=True)

    all_imgs = sorted(p for p in img_root.rglob("*") if p.suffix.lower() in EXTS)
    if args.limit > 0:
        all_imgs = all_imgs[: args.limit]

    todo = []
    skipped = 0
    for p in all_imgs:
        marker = cap_dir / f"{p.stem}.qwen"
        if marker.exists() and not args.force:
            skipped += 1
            continue
        todo.append(p)

    total = len(all_imgs)
    print(f"[recaption] img_root={img_root}")
    print(f"[recaption] cap_dir={cap_dir}")
    print(f"[recaption] 총 {total}장 | 이미 완료 {skipped}장 | 처리 {len(todo)}장")
    print(f"[recaption] dtype={args.dtype} max_side={args.max_side} max_tokens={args.max_tokens}")

    if not todo:
        print("[recaption] 할 일 없음.")
        return 0

    try:
        from PIL import Image
    except ImportError:
        print("[recaption] Pillow 필요: pip install pillow"); return 2

    cap = QwenKoCaptioner(dtype=args.dtype)

    t0 = time.time()
    fail = 0
    for i, p in enumerate(todo, 1):
        if _STOP:
            print(f"[recaption] 중단됨 — {i-1}/{len(todo)} 처리 완료.")
            break
        try:
            im = Image.open(p).convert("RGB")
            text = cap.caption(im, max_new_tokens=args.max_tokens,
                               max_image_side=args.max_side)
            if not text:
                text = "(캡션 생성 실패)"
                fail += 1
        except Exception as e:
            text = f"(ERROR: {type(e).__name__})"
            fail += 1

        tp = cap_dir / f"{p.stem}.txt"
        tp.write_text(text, encoding="utf-8")
        marker = cap_dir / f"{p.stem}.qwen"
        marker.write_text("", encoding="utf-8")

        if i % 10 == 0 or i == len(todo):
            dt = time.time() - t0
            rate = i / dt if dt > 0 else 0
            eta = (len(todo) - i) / rate if rate > 0 else 0
            print(f"[{i}/{len(todo)}] {p.name}  "
                  f"({rate:.2f} img/s, ETA {eta/60:.1f}분, fail={fail})")
            print(f"   └─ {text[:80]}")

    dt = time.time() - t0
    print(f"\n[recaption] 완료: {len(todo)}장 / {dt/60:.1f}분 / 실패 {fail}장")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
