"""다른 PC 에서 pull 받은 후 registry.json 의 abs 경로를 현재 PC 의 raw_DB 위치로 정규화.

배경:
  registry.json 의 "abs" 필드에 PC 별 절대경로 저장됨 (예: C:/yssong/.../Data/raw_DB/...).
  다른 PC 에서 pull 받으면 이 경로가 무효 → 검색 결과 클릭 시 파일 미존재.

작업:
  1. ROOT/Data/raw_DB 위치 기준으로 모든 registry 의 "abs" 갱신
     - registry key (예: "YS_1차/file.jpg") → ROOT/Data/raw_DB/<domain>/<key>
  2. abs_aliases — 디스크에 존재하는 것만 갱신, 나머지 제거 (PC 잔재)
  3. .bak.<timestamp> 자동 백업

사용:
  python scripts/normalize_registry_paths.py             # 모든 도메인 정규화
  python scripts/normalize_registry_paths.py --dry-run   # 변경 없이 보고만
  python scripts/normalize_registry_paths.py --domain Img
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("[normalize_registry_paths] 시작", flush=True)

ROOT = Path(__file__).resolve().parents[1]
RAW_DB = ROOT / "Data" / "raw_DB"
EMB_DB = ROOT / "Data" / "embedded_DB"
DOMAINS = ["Doc", "Img", "Movie", "Rec"]


def normalize_path(p: str) -> str:
    """경로 문자열 정규화 (포워드 슬래시)."""
    return str(p).replace("\\", "/")


def fix_domain(dom: str, dry_run: bool) -> dict:
    reg_path = EMB_DB / dom / "registry.json"
    if not reg_path.exists():
        return {"domain": dom, "skipped": True, "reason": "registry.json 없음"}

    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    n = len(reg)
    raw_dom = RAW_DB / dom

    n_abs_changed = 0
    n_alias_kept = 0
    n_alias_removed = 0
    n_missing = 0

    for key, entry in reg.items():
        if not isinstance(entry, dict):
            continue

        # 1. abs — registry key 기반으로 재생성
        new_abs = normalize_path(raw_dom / key)
        if entry.get("abs") != new_abs:
            entry["abs"] = new_abs
            n_abs_changed += 1
        # 디스크 존재 여부
        if not Path(new_abs).is_file():
            n_missing += 1

        # 2. abs_aliases — 디스크 존재하는 것만 유지
        aliases = entry.get("abs_aliases") or []
        if aliases:
            kept: list[str] = []
            for a in aliases:
                ap = Path(a)
                if ap.is_file():
                    kept.append(normalize_path(ap))
                    n_alias_kept += 1
                else:
                    n_alias_removed += 1
            if kept:
                entry["abs_aliases"] = kept
            else:
                entry.pop("abs_aliases", None)

    print(f"\n=== {dom} ===", flush=True)
    print(f"  total entries:        {n}", flush=True)
    print(f"  abs 갱신:             {n_abs_changed}", flush=True)
    print(f"  디스크 미존재 (raw):  {n_missing}", flush=True)
    print(f"  alias 유지:           {n_alias_kept}", flush=True)
    print(f"  alias 제거 (PC잔재):  {n_alias_removed}", flush=True)

    if dry_run:
        print("  (dry-run: 저장 안 함)", flush=True)
        return {"domain": dom, "abs_changed": n_abs_changed,
                "missing": n_missing, "dry_run": True}

    if n_abs_changed > 0 or n_alias_removed > 0:
        bak = reg_path.with_suffix(reg_path.suffix + f".bak.{int(time.time())}")
        shutil.copy2(reg_path, bak)
        reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"  저장: {reg_path.name} (백업: {bak.name})", flush=True)
    else:
        print("  변경 없음 — 이미 정규화됨", flush=True)

    return {"domain": dom, "abs_changed": n_abs_changed,
            "missing": n_missing, "alias_kept": n_alias_kept}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--domain", choices=DOMAINS)
    args = parser.parse_args()

    domains = [args.domain] if args.domain else DOMAINS
    print(f"ROOT: {ROOT}", flush=True)
    print(f"RAW_DB: {RAW_DB}", flush=True)
    print(f"대상: {', '.join(domains)} ({'dry-run' if args.dry_run else 'apply'})", flush=True)

    if not RAW_DB.is_dir():
        print(f"\n[ERROR] {RAW_DB} 없음 — 먼저 raw_DB 데이터를 배치하세요", flush=True)
        return 2

    results = [fix_domain(d, args.dry_run) for d in domains]

    print("\n" + "=" * 60, flush=True)
    print("요약", flush=True)
    print("=" * 60, flush=True)
    for r in results:
        if r.get("skipped"):
            print(f"  {r['domain']}: skipped — {r.get('reason')}", flush=True)
        else:
            mark = "⚠️" if r.get("missing", 0) > 0 else "✓"
            print(f"  {mark} {r['domain']}: abs 갱신 {r.get('abs_changed', 0)}, "
                  f"디스크 미존재 {r.get('missing', 0)}", flush=True)

    # 디스크 미존재 안내
    total_missing = sum(r.get("missing", 0) for r in results if not r.get("skipped"))
    if total_missing > 0:
        print(f"\n⚠️ 디스크 미존재 파일 {total_missing}건 — raw_DB 데이터 배치 확인 필요", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
