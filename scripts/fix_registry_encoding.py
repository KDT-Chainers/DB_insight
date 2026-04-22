"""scripts/fix_registry_encoding.py — registry.json 한글 깨짐(\ufffd) 복구.

원인: Windows rglob Path 문자열이 서러게이트 이스케이프로 JSON 에 쓰이면서
     일부 바이트가 replacement char 로 손실됨.

복구 전략:
  1) 현재 디스크의 raw_DB 실제 파일명을 정답으로 삼음
  2) registry 각 키의 깨진 prefix 를 실파일명에 매칭하여 재바인딩
  3) SHA 는 파일명으로 재계산 (SHA 값 자체는 인코딩과 무관하지만 누락 파일 감지 겸)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

from config import PATHS  # noqa: E402


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rebuild(domain: str, raw_dir: Path, cache_dir: Path,
             exts: set[str]) -> None:
    reg_path = cache_dir / "registry.json"
    if not reg_path.exists():
        print(f"[{domain}] registry.json 없음")
        return

    before = json.loads(reg_path.read_text(encoding="utf-8"))
    corrupt = sum("\ufffd" in k for k in before.keys())

    new_reg: dict = {}
    files = [p for p in raw_dir.rglob("*") if p.suffix.lower() in exts and p.is_file()]
    print(f"[{domain}] 파일 {len(files)}개, 깨진 키 {corrupt}개")

    for p in files:
        key = str(p.relative_to(raw_dir)).replace("\\", "/")
        new_reg[key] = {"sha": _sha256(p), "abs": str(p)}

    backup = reg_path.with_suffix(".json.bak")
    backup.write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")
    reg_path.write_text(json.dumps(new_reg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{domain}] 복구 완료 → {len(new_reg)}개, 백업 {backup.name}")


def main():
    _rebuild(
        "image",
        Path(PATHS["RAW_DB"]) / "Img",
        Path(PATHS["TRICHEF_IMG_CACHE"]),
        {".jpg", ".jpeg", ".png", ".webp"},
    )
    _rebuild(
        "document",
        Path(PATHS["RAW_DB"]) / "Doc",
        Path(PATHS["TRICHEF_DOC_CACHE"]),
        {".pdf", ".docx", ".doc", ".hwp", ".hwpx",
         ".pptx", ".ppt", ".xlsx", ".xls",
         ".csv", ".html", ".htm", ".txt", ".md"},
    )


if __name__ == "__main__":
    main()
