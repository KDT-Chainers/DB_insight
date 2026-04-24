"""DI_TriCHEF/captioner/sample_dryrun.py

Qwen2-VL-2B-Instruct 한국어 캡션 드라이런 — 1~N장 샘플.

용도: 전체 재캡션 배치 전 모델 동작/품질 선검증.
  · 모델 다운로드(최초 1회, ~5GB) 및 bf16/GPU 작동 확인
  · 기존 BLIP 캡션(있으면) 과 Qwen KR 캡션 나란히 출력

실행:
    cd DB_insight
    python DI_TriCHEF/captioner/sample_dryrun.py                 # 기본 5장
    python DI_TriCHEF/captioner/sample_dryrun.py --n 10
    python DI_TriCHEF/captioner/sample_dryrun.py --images a.jpg b.png

종료 후 리포트: compare_report.md (스크립트 옆) 생성.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "App" / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from captioner.qwen_vl_ko import QwenKoCaptioner


def _collect_images(explicit: list[str] | None, n: int) -> list[Path]:
    if explicit:
        return [Path(p) for p in explicit if Path(p).exists()]
    try:
        from config import PATHS
        img_root = Path(PATHS["RAW_DB"]) / "Img"
    except Exception:
        img_root = ROOT / "Data" / "raw_DB" / "Img"
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    pool = [p for p in img_root.rglob("*") if p.suffix.lower() in exts]
    pool.sort()
    return pool[:n]


def _blip_caption_for(img: Path) -> str:
    """기존 BLIP 캡션 텍스트 (TRICHEF_IMG_EXTRACT/captions/<stem>.txt) — 없으면 빈 문자열."""
    try:
        from config import PATHS
        from embedders.trichef.caption_io import load_caption
        from embedders.trichef.doc_page_render import stem_key_for
        cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
        key = stem_key_for(img.name)
        text = load_caption(cap_dir, key)
        if text:
            return text
        return load_caption(cap_dir, img.stem)
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--images", nargs="*", default=None)
    ap.add_argument("--dtype", default="bfloat16",
                    choices=["bfloat16", "float16", "float32"])
    args = ap.parse_args()

    images = _collect_images(args.images, args.n)
    if not images:
        print("[dryrun] ⚠️  샘플 이미지를 찾지 못했습니다.")
        return 1

    print(f"[dryrun] 샘플 {len(images)}장 / dtype={args.dtype}")
    cap = QwenKoCaptioner(dtype=args.dtype)

    try:
        from PIL import Image
    except ImportError:
        print("[dryrun] Pillow 필요: pip install pillow"); return 2

    rows: list[tuple[Path, str, str]] = []
    for i, p in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {p.name}")
        try:
            im = Image.open(p).convert("RGB")
            ko = cap.caption(im)
        except Exception as e:
            ko = f"(ERROR: {e})"
        blip = _blip_caption_for(p)
        rows.append((p, blip, ko))
        print(f"  BLIP: {blip or '(없음)'}")
        print(f"  Qwen: {ko}\n")

    report = Path(__file__).resolve().parent / "compare_report.md"
    with report.open("w", encoding="utf-8") as f:
        f.write("# Qwen KR vs BLIP 캡션 비교\n\n")
        f.write(f"- sample N: {len(rows)}\n- dtype: {args.dtype}\n\n")
        f.write("| # | 파일 | BLIP(EN) | Qwen(KR) |\n|---|---|---|---|\n")
        for i, (p, b, k) in enumerate(rows, 1):
            f.write(f"| {i} | `{p.name}` | {b or '-'} | {k} |\n")
    print(f"[dryrun] 리포트 → {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
