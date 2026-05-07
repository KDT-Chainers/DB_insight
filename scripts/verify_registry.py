"""Registry 정합성 4-way 검증 도구.

검사 대상:
  1. raw_DB 디스크 파일 ↔ registry.json
  2. registry.json ↔ embedded_DB .npy 행 수
  3. .npy ↔ ChromaDB 컬렉션 count
  4. registry abs path ↔ 실제 디스크 파일 (orphan)

도메인: Doc, Img, Movie, Rec

사용:
    python scripts/verify_registry.py
    python scripts/verify_registry.py --domain Img
    python scripts/verify_registry.py --json report.json

GPU 사용 X — disk read-only + ChromaDB metadata only.
인덱싱 작업과 병렬 실행 안전.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAW_DB = ROOT / "Data" / "raw_DB"
EMBEDDED_DB = ROOT / "Data" / "embedded_DB"
CHROMA_DIR = EMBEDDED_DB / "trichef_chroma"

# 도메인 → (raw_DB 하위, embedded_DB 하위, ChromaDB 컬렉션 prefix)
DOMAINS = {
    "Doc":   {"raw": "Doc",   "emb": "Doc",   "collection": "trichef_doc_page",
              "npy_files": ["cache_doc_page_Re.npy", "cache_doc_page_Im.npy", "cache_doc_page_Z.npy"]},
    "Img":   {"raw": "Img",   "emb": "Img",   "collection": "trichef_image",
              "npy_files": ["cache_img_Re_siglip2.npy", "cache_img_Im_e5cap.npy", "cache_img_Z_dinov2.npy"]},
    "Movie": {"raw": "Movie", "emb": "Movie", "collection": "trichef_movie",
              "npy_files": ["movie_Re.npy", "movie_Im.npy", "movie_Z.npy"]},
    "Rec":   {"raw": "Rec",   "emb": "Rec",   "collection": "trichef_music",
              "npy_files": ["music_Re.npy", "music_Im.npy", "music_Z.npy"]},
}

DOC_EXTS   = {".pdf", ".docx", ".doc", ".hwp", ".hwpx", ".pptx", ".ppt", ".txt", ".md", ".html", ".htm", ".xlsx", ".xls"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma", ".opus"}

DOMAIN_EXTS = {
    "Doc": DOC_EXTS, "Img": IMAGE_EXTS, "Movie": VIDEO_EXTS, "Rec": AUDIO_EXTS,
}


def count_raw_files(domain: str) -> int:
    """raw_DB 디스크에서 도메인별 지원 확장자 파일 개수."""
    root = RAW_DB / DOMAINS[domain]["raw"]
    if not root.is_dir():
        return 0
    exts = DOMAIN_EXTS[domain]
    n = 0
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            n += 1
    return n


def load_registry(domain: str) -> dict:
    p = EMBEDDED_DB / DOMAINS[domain]["emb"] / "registry.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def count_npy_rows(domain: str) -> int | None:
    """첫 번째 .npy 파일의 행 수. 모든 .npy 가 같은 행 수여야 정상."""
    cache_dir = EMBEDDED_DB / DOMAINS[domain]["emb"]
    files = DOMAINS[domain]["npy_files"]
    counts = []
    for fn in files:
        path = cache_dir / fn
        if not path.exists():
            continue
        try:
            import numpy as np
            arr = np.load(path, mmap_mode="r")
            counts.append(int(arr.shape[0]))
        except Exception:
            return None
    if not counts:
        return None
    if len(set(counts)) > 1:
        return -1   # 행 수 불일치 — 심각한 문제
    return counts[0]


def chroma_count(domain: str) -> int | None:
    """ChromaDB 컬렉션의 항목 수."""
    if not CHROMA_DIR.exists():
        return None
    try:
        import chromadb
        from chromadb.config import Settings
        client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        col = client.get_or_create_collection(
            name=DOMAINS[domain]["collection"],
            metadata={"hnsw:space": "cosine"},
        )
        return col.count()
    except Exception as e:
        print(f"  ⚠️  ChromaDB 조회 실패 ({domain}): {e}", file=sys.stderr)
        return None


def find_orphans(registry: dict) -> list[str]:
    """registry 에 등록되었으나 disk 에 없는 파일."""
    out = []
    for entry in registry.values():
        abs_path = entry.get("abs") if isinstance(entry, dict) else None
        if abs_path and not Path(abs_path).exists():
            out.append(abs_path)
    return out


def find_missing(domain: str, registry: dict) -> list[str]:
    """disk 에 있지만 registry 에 없는 파일."""
    root = RAW_DB / DOMAINS[domain]["raw"]
    if not root.is_dir():
        return []
    exts = DOMAIN_EXTS[domain]
    indexed_abs = set()
    for entry in registry.values():
        if isinstance(entry, dict):
            ab = entry.get("abs")
            if ab:
                indexed_abs.add(str(Path(ab).resolve()).lower())
    out = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            key = str(p.resolve()).lower()
            if key not in indexed_abs:
                out.append(str(p))
    return out


def verify_domain(domain: str, verbose: bool = True) -> dict:
    raw_n = count_raw_files(domain)
    reg = load_registry(domain)
    reg_n = len(reg)
    npy_n = count_npy_rows(domain)
    chr_n = chroma_count(domain)
    orphans = find_orphans(reg)
    missing = find_missing(domain, reg)

    # Doc/Img: registry 1 entry == 1 file. Movie/Rec: 1 entry per segment. npy_n != reg_n 가능.
    is_segment_based = domain in ("Movie", "Rec")
    npy_match = (
        "n/a" if is_segment_based
        else ("OK" if npy_n == reg_n else f"MISMATCH ({npy_n} vs {reg_n})")
    )
    chr_match = (
        "n/a" if is_segment_based
        else ("OK" if chr_n == reg_n else f"MISMATCH ({chr_n} vs {reg_n})")
    )

    result = {
        "domain": domain,
        "raw_files": raw_n,
        "registry_entries": reg_n,
        "npy_rows": npy_n,
        "chroma_count": chr_n,
        "orphans": orphans,
        "missing": missing,
        "npy_match": npy_match,
        "chroma_match": chr_match,
    }

    if verbose:
        print(f"\n=== {domain} ===")
        print(f"  raw_DB files:   {raw_n}")
        print(f"  registry:       {reg_n}")
        print(f"  .npy rows:      {npy_n}")
        print(f"  ChromaDB count: {chr_n}")
        print(f"  npy match:      {npy_match}")
        print(f"  chroma match:   {chr_match}")
        print(f"  orphans (disk-missing): {len(orphans)}")
        print(f"  missing (not-indexed):  {len(missing)}")
        if orphans[:3]:
            print("  orphan 샘플:")
            for o in orphans[:3]:
                print(f"    - {o[-80:]}")
        if missing[:3]:
            print("  missing 샘플:")
            for m in missing[:3]:
                print(f"    - {m[-80:]}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Registry 정합성 검증")
    parser.add_argument("--domain", choices=list(DOMAINS.keys()),
                        help="단일 도메인만 (기본: 전체)")
    parser.add_argument("--json", help="결과 JSON 저장")
    parser.add_argument("--quiet", action="store_true", help="요약만 출력")
    args = parser.parse_args()

    domains = [args.domain] if args.domain else list(DOMAINS.keys())
    print(f"Registry 정합성 검증 ({', '.join(domains)})")
    print(f"  raw_DB:    {RAW_DB}")
    print(f"  embedded:  {EMBEDDED_DB}")

    results = [verify_domain(d, verbose=not args.quiet) for d in domains]

    print("\n" + "=" * 80)
    print("종합")
    print("=" * 80)
    print(f"{'도메인':<8s}{'raw':>8s}{'reg':>8s}{'npy':>8s}{'chroma':>10s}{'orph':>8s}{'miss':>8s}")
    for r in results:
        print(f"{r['domain']:<8s}{r['raw_files']:>8d}{r['registry_entries']:>8d}"
              f"{(r['npy_rows'] or 0):>8d}{(r['chroma_count'] or 0):>10d}"
              f"{len(r['orphans']):>8d}{len(r['missing']):>8d}")

    has_issues = any(
        r["orphans"] or r["missing"]
        or (r["npy_match"] not in ("OK", "n/a"))
        or (r["chroma_match"] not in ("OK", "n/a"))
        for r in results
    )
    if has_issues:
        print("\n⚠️  정합성 이슈 발견 — 위 표 확인")
    else:
        print("\n✅ 모든 도메인 정합성 OK")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nJSON 저장: {args.json}")

    return 1 if has_issues else 0


if __name__ == "__main__":
    sys.exit(main())
