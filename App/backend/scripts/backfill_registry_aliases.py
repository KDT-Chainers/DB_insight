"""[D-1] registry.json 의 abs_aliases 일괄 backfill.

배경:
  P5 코드 패치(incremental_runner.py:838) 이후 신규 인덱싱은 원본 경로를
  abs_aliases 에 자동 등록. 그러나 기존 staged/* 엔트리 중 abs_aliases 가
  비어있는 항목은 registry_lookup 으로 "indexed=True" 매칭이 안 되어
  UI 에서 영구히 "신규" 로 표시됨.

전략:
  1) Img/Doc registry 의 staged/* 키를 모두 수집 (sha 인덱스 구축)
  2) raw_DB/(Img|Doc) 하위 모든 파일 순회 (재귀)
  3) 각 파일의 SHA-256 계산
  4) registry sha 와 일치하면 그 엔트리의 abs_aliases 에 추가 (중복 제외)
  5) 변경 시 registry.json 저장

스킵 대상: .omc/, test/ 폴더 (사용자가 명시 제외 원함)

성능: SHA-256 약 100MB/s → 50GB raw_DB 약 8분
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "App" / "backend"))
from config import PATHS  # noqa: E402

RAW_DB = Path(PATHS["RAW_DB"])
SKIP_DIRS = {".omc", "test"}
DOMAINS = {
    "Img": (Path(PATHS["TRICHEF_IMG_CACHE"]) / "registry.json",
            {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".heif"}),
    "Doc": (Path(PATHS["TRICHEF_DOC_CACHE"]) / "registry.json",
            {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
             ".hwp", ".hwpx", ".txt", ".md", ".csv", ".html", ".htm",
             ".odt", ".odp", ".ods", ".rtf"}),
}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_skipped(p: Path) -> bool:
    """경로 어딘가에 .omc/ 또는 test/ 폴더가 있으면 skip."""
    for part in p.parts:
        if part in SKIP_DIRS:
            return True
    return False


def backfill_domain(domain: str, reg_path: Path, exts: set[str],
                    *, dry_run: bool = False) -> dict:
    if not reg_path.exists():
        print(f"  [{domain}] registry.json 없음 — skip")
        return {"updated": 0, "scanned": 0, "matched": 0}
    print(f"\n=== {domain} backfill ===")
    reg = json.loads(reg_path.read_text(encoding="utf-8"))

    # 1) sha → (key, entry) 인덱스 구축 — abs_aliases 비어있는 항목만 후보
    sha_to_keys: dict[str, list[str]] = {}
    candidates = 0
    for k, v in reg.items():
        if not isinstance(v, dict):
            continue
        sha = v.get("sha")
        if not sha:
            continue
        aliases = v.get("abs_aliases") or []
        # staged/* 키 + alias 비어있음 → 후보
        if k.startswith("staged/") and not aliases:
            sha_to_keys.setdefault(sha, []).append(k)
            candidates += 1
    print(f"  alias 누락 staged 엔트리: {candidates}건")

    if not sha_to_keys:
        print(f"  → backfill 대상 없음")
        return {"updated": 0, "scanned": 0, "matched": 0}

    # 2) raw_DB/<domain>/ 하위 파일 순회
    raw_dir = RAW_DB / domain
    if not raw_dir.exists():
        print(f"  {raw_dir} 없음 — skip")
        return {"updated": 0, "scanned": 0, "matched": 0}

    scanned = 0
    matched = 0
    updated = 0
    t0 = time.time()
    for fpath in raw_dir.rglob("*"):
        if not fpath.is_file():
            continue
        if fpath.suffix.lower() not in exts:
            continue
        if _is_skipped(fpath):
            continue
        # staged 경로 자체는 백필 대상 아님 (이미 등록된 위치)
        if "staged" in fpath.parts:
            continue
        scanned += 1
        if scanned % 500 == 0:
            elapsed = time.time() - t0
            print(f"    스캔 {scanned}건 ({elapsed:.0f}s, {scanned/max(elapsed,1):.0f} file/s)  매칭 {matched}건")
        try:
            sha = _sha256(fpath)
        except Exception as e:
            continue
        keys = sha_to_keys.get(sha)
        if not keys:
            continue
        matched += 1
        abs_str = str(fpath.resolve())
        for k in keys:
            ent = reg[k]
            aliases = ent.get("abs_aliases") or []
            if abs_str not in aliases:
                aliases.append(abs_str)
                ent["abs_aliases"] = aliases
                updated += 1

    if updated > 0 and not dry_run:
        reg_path.write_text(
            json.dumps(reg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  ✓ registry 저장: {updated}건 alias 추가 (스캔 {scanned}건, 매칭 {matched}건)")
    elif dry_run:
        print(f"  [dry-run] {updated}건 추가 예정 (스캔 {scanned}건, 매칭 {matched}건) — 미저장")
    else:
        print(f"  변경 없음 (스캔 {scanned}건)")

    return {"updated": updated, "scanned": scanned, "matched": matched}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="실제 저장 없이 시뮬레이션")
    ap.add_argument("--domain", choices=["Img", "Doc", "all"], default="all")
    args = ap.parse_args()

    t0 = time.time()
    print(f"=== Registry abs_aliases backfill ===")
    print(f"  RAW_DB: {RAW_DB}")
    print(f"  skip dirs: {SKIP_DIRS}")
    print(f"  dry-run: {args.dry_run}")
    total = {"updated": 0, "scanned": 0, "matched": 0}
    for dom, (rp, exts) in DOMAINS.items():
        if args.domain != "all" and args.domain != dom:
            continue
        r = backfill_domain(dom, rp, exts, dry_run=args.dry_run)
        for k in total:
            total[k] += r[k]
    print(f"\n=== 합계: 스캔 {total['scanned']}건, 매칭 {total['matched']}건, alias 추가 {total['updated']}건 "
          f"({time.time()-t0:.0f}초) ===")


if __name__ == "__main__":
    main()
