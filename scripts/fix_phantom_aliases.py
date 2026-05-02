"""Phantom 파일을 registry 의 같은 SHA entry alias 로 등록.

이미 임베딩 완료된 파일이지만 SHA-dedup guard 로 registry 등록이 skip 된
"phantom" 파일들을 식별하여, 같은 SHA 의 기존 entry["abs_aliases"] 에 추가.

이로써 registry_lookup 이 alias 인덱스를 통해 "indexed" 로 판정하게 됨
→ 인덱싱 UI 의 "신규 N" 무한 루프 차단.

사용:
    python scripts/fix_phantom_aliases.py                  # 전체 도메인
    python scripts/fix_phantom_aliases.py --dry-run        # 변경 없이 보고
    python scripts/fix_phantom_aliases.py --domain Img     # 단일 도메인
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import sys
import time
import shutil
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
RAW_DB = ROOT / "Data" / "raw_DB"
EMBEDDED_DB = ROOT / "Data" / "embedded_DB"

DOMAIN_EXT = {
    "Img":   {"*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp", "*.bmp"},
    "Doc":   {"*.pdf"},
    "Movie": {"*.mp4", "*.avi", "*.mov", "*.mkv", "*.webm"},
    "Rec":   {"*.wav", "*.mp3", "*.m4a", "*.ogg", "*.flac"},
}


def sha256_file(p: Path, buf: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            data = f.read(buf)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def collect_disk_files(domain: str) -> list[Path]:
    out: list[Path] = []
    domdir = RAW_DB / domain
    if not domdir.is_dir():
        return out
    exts = DOMAIN_EXT.get(domain, set())
    if not exts:
        return out
    for sub in domdir.iterdir():
        if not sub.is_dir() or sub.name == "staged":
            continue
        for ext in exts:
            for p in sub.rglob(ext):
                out.append(p)
            # case-insensitive
            for p in sub.rglob(ext.upper()):
                out.append(p)
    # dedupe
    seen, uniq = set(), []
    for p in out:
        s = str(p.resolve()).lower()
        if s in seen:
            continue
        seen.add(s)
        uniq.append(p)
    return uniq


def _norm(p: str) -> str:
    return str(Path(p).resolve()).lower().replace("\\", "/") if p else ""


def fix_domain(domain: str, dry_run: bool) -> dict:
    reg_path = EMBEDDED_DB / domain / "registry.json"
    if not reg_path.exists():
        return {"domain": domain, "skipped": True, "reason": "registry.json 없음"}
    reg = json.loads(reg_path.read_text(encoding="utf-8"))

    # registry 의 abs + abs_aliases 정규화 인덱스
    indexed_paths = set()
    for k, v in reg.items():
        if not isinstance(v, dict):
            continue
        ap = v.get("abs")
        if ap:
            indexed_paths.add(_norm(ap))
        for a in v.get("abs_aliases") or []:
            if a:
                indexed_paths.add(_norm(a))

    # SHA → registry key 매핑
    sha_to_key = {}
    for k, v in reg.items():
        if isinstance(v, dict):
            s = v.get("sha")
            if s:
                sha_to_key[s] = k

    # 디스크 파일 중 indexed_paths 에 없는 것
    disk_files = collect_disk_files(domain)
    phantoms = [p for p in disk_files if _norm(str(p)) not in indexed_paths]
    print(f"\n=== {domain} ===")
    print(f"  registry entries:        {len(reg)}")
    print(f"  registry indexed paths:  {len(indexed_paths)}")
    print(f"  disk files:              {len(disk_files)}")
    print(f"  phantom 후보:            {len(phantoms)}")

    if not phantoms:
        return {"domain": domain, "phantoms": 0, "linked": 0}

    # 각 phantom SHA 계산 → 매칭되는 entry 의 abs_aliases 에 추가
    linked = 0
    no_match: list[str] = []
    changed_keys: set = set()
    for p in phantoms:
        try:
            sha = sha256_file(p)
        except Exception as e:
            print(f"  ⚠️  SHA 계산 실패: {p} — {e}")
            continue
        match_key = sha_to_key.get(sha)
        if not match_key:
            no_match.append(str(p))
            continue
        entry = reg[match_key]
        aliases = entry.get("abs_aliases") or []
        ap_str = str(p.resolve())
        if any(_norm(a) == _norm(ap_str) for a in aliases):
            continue   # 이미 등록됨
        aliases.append(ap_str)
        entry["abs_aliases"] = aliases
        changed_keys.add(match_key)
        linked += 1
        print(f"  + alias: {p.name} → {match_key}")

    print(f"  연결됨:   {linked}")
    print(f"  매칭 안됨: {len(no_match)}")
    for n in no_match[:5]:
        print(f"    × {n}")

    if dry_run:
        print("  (dry-run: 변경 없음)")
        return {"domain": domain, "phantoms": len(phantoms),
                "linked": linked, "no_match": len(no_match), "dry_run": True}

    if linked > 0:
        bak = reg_path.with_suffix(f".json.bak.{int(time.time())}")
        shutil.copy2(reg_path, bak)
        reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"  registry 갱신 + 백업: {bak.name}")

    return {"domain": domain, "phantoms": len(phantoms),
            "linked": linked, "no_match": len(no_match), "dry_run": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="phantom 파일 alias 등록")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--domain", choices=list(DOMAIN_EXT.keys()))
    args = parser.parse_args()

    domains = [args.domain] if args.domain else list(DOMAIN_EXT.keys())
    print(f"phantom alias 등록: {', '.join(domains)} "
          f"({'dry-run' if args.dry_run else 'apply'})")
    results = [fix_domain(d, args.dry_run) for d in domains]
    print("\n" + "=" * 60)
    print("요약")
    print("=" * 60)
    for r in results:
        if r.get("skipped"):
            print(f"  {r['domain']}: 건너뜀 ({r.get('reason')})")
        else:
            print(f"  {r['domain']}: phantoms {r.get('phantoms', 0)}, "
                  f"linked {r.get('linked', 0)}, "
                  f"no_match {r.get('no_match', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
