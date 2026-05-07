"""캐시 정합성 자동 정리 — registry / ChromaDB / 물리 파일 / extracted_DB 일관 유지.

역할 분리:
  - dedupe_registry.py : registry.json 내 중복 entry 제거 + .npy/ids/Chroma 동기
  - reconcile_caches.py: registry 를 SOURCE OF TRUTH 로 두고 그 외 산출물 정리

대상 (registry 에 없는 모든 잔여물):
  1. ChromaDB orphan entries — registry 에서 제거된 ID 가 Chroma 에 남아있는 경우
  2. raw_DB/<domain>/staged/ 물리 파일 — registry 에 등록되지 않은 staged 복사본
  3. extracted_DB 캡션/페이지 이미지 — registry 와 매칭 안 되는 파일
  4. OS Temp app_movie_*/app_music_* — 1시간 이상 stale 디렉토리

전제:
  - 백엔드(127.0.0.1:5001) 정지 상태
  - registry.json 은 이미 dedupe_registry.py 로 정리 완료

사용:
    python scripts/reconcile_caches.py                 # 전체, apply
    python scripts/reconcile_caches.py --dry-run       # 변경 없이 보고
    python scripts/reconcile_caches.py --skip-chroma   # Chroma 만 건너뜀
    python scripts/reconcile_caches.py --skip-staged   # staged 파일 건너뜀
"""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMBEDDED_DB = ROOT / "Data" / "embedded_DB"
EXTRACTED_DB = ROOT / "Data" / "extracted_DB"
RAW_DB = ROOT / "Data" / "raw_DB"
CHROMA_DIR = EMBEDDED_DB / "trichef"

DOMAIN_CFG = {
    "Img": {
        "registry": EMBEDDED_DB / "Img" / "registry.json",
        "chroma_collection": "trichef_image",
        "raw_subdir": RAW_DB / "Img",
        "staged_dir": RAW_DB / "Img" / "staged",
        "extract_dir": EXTRACTED_DB / "Img",
    },
    "Doc": {
        "registry": EMBEDDED_DB / "Doc" / "registry.json",
        "chroma_collection": "trichef_doc_page",
        "raw_subdir": RAW_DB / "Doc",
        "staged_dir": RAW_DB / "Doc" / "staged",
        "extract_dir": EXTRACTED_DB / "Doc",
    },
}


def _backend_running() -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", 5001), timeout=1)
        s.close()
        return True
    except Exception:
        return False


def _load_registry(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def reconcile_chroma(domain: str, dry_run: bool) -> dict:
    """registry 에 없는 entry 를 ChromaDB 에서 제거."""
    cfg = DOMAIN_CFG[domain]
    reg = _load_registry(cfg["registry"])
    keep_ids = set(reg.keys())
    if not keep_ids:
        return {"domain": domain, "skipped": True, "reason": "registry empty"}
    try:
        import chromadb
        from chromadb.config import Settings
        client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        col = client.get_or_create_collection(
            name=cfg["chroma_collection"],
            metadata={"hnsw:space": "cosine"},
        )
        # SQLite SQL variable 한계(32766) 회피 — 페이지네이션으로 전체 ID 수집.
        all_ids: list[str] = []
        PAGE = 5000
        offset = 0
        while True:
            res = col.get(limit=PAGE, offset=offset, include=[])
            batch = res.get("ids", [])
            all_ids.extend(batch)
            if len(batch) < PAGE:
                break
            offset += PAGE
        n_total = len(all_ids)
        # Doc 의 chroma id 는 page_images/<stem>/p0001.png 형식 — registry key (file-level) 와 다름.
        # 따라서 prefix 매칭으로 keep 결정.
        if domain == "Doc":
            from embedders.trichef.doc_page_render import stem_key_for
            stem_keep = {stem_key_for(k) for k in keep_ids}
            to_delete = []
            for cid in all_ids:
                parts = Path(cid).parts
                if len(parts) >= 2 and parts[0] == "page_images":
                    stem = parts[1]
                    if stem not in stem_keep:
                        to_delete.append(cid)
                else:
                    to_delete.append(cid)  # 형식 모름 → 안전하게 제거
        else:
            to_delete = [i for i in all_ids if i not in keep_ids]
        n_remove = len(to_delete)
        # [안전 가드] 80% 이상 삭제는 schema 불일치 가능성 → 자동 abort.
        # Doc 의 경우 registry stem 형식 (name__hash) ≠ chroma stem 형식 (name)
        # 으로 mismatch 가 일어나면 거의 모든 entry 가 "삭제 대상" 으로 보임.
        # 이 경우 정상 데이터를 잘못 지우는 것이 됨.
        if n_total > 0 and (n_remove / n_total) > 0.80:
            return {"domain": domain, "chroma_total": n_total,
                    "to_delete": n_remove,
                    "aborted": True,
                    "reason": "80%+ 삭제는 schema 불일치 가능성 → 수동 검토 필요"}
        if dry_run:
            return {"domain": domain, "chroma_total": n_total,
                    "to_delete": n_remove, "dry_run": True}
        if to_delete:
            # SQL 변수 한계 회피 — 작은 chunk 로 분할.
            CHUNK = 500
            for i in range(0, len(to_delete), CHUNK):
                col.delete(ids=to_delete[i:i + CHUNK])
        return {"domain": domain, "chroma_total": n_total,
                "deleted": n_remove, "after": n_total - n_remove}
    except Exception as e:
        return {"domain": domain, "error": str(e)[:200]}


def reconcile_staged(domain: str, dry_run: bool) -> dict:
    """raw_DB/<domain>/staged/ 의 물리 파일 중 registry 에 없는 것 제거."""
    cfg = DOMAIN_CFG[domain]
    staged_dir = cfg["staged_dir"]
    if not staged_dir.is_dir():
        return {"domain": domain, "skipped": True, "reason": "staged dir 없음"}

    reg = _load_registry(cfg["registry"])
    # staged key 형식: "staged/<hash>/<name>"
    keep_paths: set[str] = set()
    for k, v in reg.items():
        if isinstance(v, dict) and v.get("staged"):
            keep_paths.add(str(Path(v["staged"]).resolve()).lower())
        elif k.startswith("staged/"):
            keep_paths.add(str((cfg["raw_subdir"] / k).resolve()).lower())

    found = 0
    removed = 0
    freed_bytes = 0
    for sub in staged_dir.iterdir():
        if not sub.is_dir():
            continue
        for f in sub.rglob("*"):
            if not f.is_file():
                continue
            found += 1
            key = str(f.resolve()).lower()
            if key in keep_paths:
                continue
            try:
                size = f.stat().st_size
            except Exception:
                size = 0
            if dry_run:
                removed += 1
                freed_bytes += size
            else:
                try:
                    f.unlink()
                    removed += 1
                    freed_bytes += size
                except Exception:
                    pass
        # 빈 디렉토리 제거
        if not dry_run:
            try:
                if not any(sub.iterdir()):
                    sub.rmdir()
            except Exception:
                pass
    return {"domain": domain, "found": found, "removed": removed,
            "freed_mb": round(freed_bytes / (1024 * 1024), 1),
            "dry_run": dry_run}


def reconcile_temp(dry_run: bool) -> dict:
    """OS Temp 의 app_movie_*/app_music_* 1h+ stale 폴더 정리.

    services/cache_janitor.py 의 기능을 standalone 으로 호출.
    """
    try:
        sys.path.insert(0, str(ROOT / "App" / "backend"))
        from services.cache_janitor import cleanup_stale_caches
        if dry_run:
            # threshold 만 체크
            import tempfile
            from pathlib import Path as _P
            root = _P(tempfile.gettempdir())
            count = sum(1 for d in root.iterdir() if d.is_dir()
                        and (d.name.startswith("app_movie_") or d.name.startswith("app_music_")))
            return {"temp_dirs": count, "dry_run": True}
        return cleanup_stale_caches()
    except Exception as e:
        return {"error": str(e)[:200]}


def main() -> int:
    parser = argparse.ArgumentParser(description="캐시 정합성 정리")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-chroma", action="store_true")
    parser.add_argument("--skip-staged", action="store_true")
    parser.add_argument("--skip-temp", action="store_true")
    parser.add_argument("--domain", choices=list(DOMAIN_CFG.keys()))
    args = parser.parse_args()

    if not args.dry_run and _backend_running():
        print("⚠️  백엔드(127.0.0.1:5001) 가 실행 중입니다. 종료 후 재시도.",
              file=sys.stderr)
        return 2

    sys.path.insert(0, str(ROOT / "App" / "backend"))

    domains = [args.domain] if args.domain else list(DOMAIN_CFG.keys())
    print(f"캐시 정합성 정리: {', '.join(domains)} ({'dry-run' if args.dry_run else 'apply'})")

    if not args.skip_chroma:
        print("\n[1/3] ChromaDB orphan 정리")
        for d in domains:
            r = reconcile_chroma(d, args.dry_run)
            print(f"  {d}: {r}")

    if not args.skip_staged:
        print("\n[2/3] raw_DB staged 물리 파일 정리")
        for d in domains:
            r = reconcile_staged(d, args.dry_run)
            print(f"  {d}: {r}")

    if not args.skip_temp:
        print("\n[3/3] OS Temp stale 디렉토리 정리")
        r = reconcile_temp(args.dry_run)
        print(f"  {r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
