"""registry 중복 entry 정리 도구.

배경:
  같은 파일이 두 가지 key 형식으로 중복 등록된 케이스:
  - 직접 경로 (canonical): "YS_1차/file.jpg" — run_image_incremental(bulk)
  - staged 해시:           "staged/abc12345/file.jpg" — embed_image_file(single)

  단일 파일 임베더가 SHA-skip 검사 시 자기 형식만 비교 → 같은 파일을 다시 등록.

작동:
  도메인별 registry 의 entry 들을 SHA 그룹화. 그룹별 1개만 keep, 나머지 제거.
    - keep 우선순위: (1) non-staged (canonical), (2) abs path 가 disk 에 존재
    - 제거 대상: staged/* 중 중복 또는 disk 미존재

부수 작업:
  - .npy 행 필터 (Re/Im/Z 3축)
  - img_ids.json / doc_page_ids.json 행 필터
  - ChromaDB 컬렉션 entry 삭제
  - 물리 staged 파일 삭제 (선택, --remove-staged-files)

안전 장치:
  - 실행 전 backend 가 stop 되어 있어야 함 (ChromaDB write lock 회피)
  - registry.json / .npy / ids.json 모두 .bak.<timestamp> 자동 백업
  - --dry-run 모드: 실제 변경 없이 카운트만 출력

사용:
    python scripts/dedupe_registry.py                         # 전체 도메인, 변경 적용
    python scripts/dedupe_registry.py --dry-run               # 변경 없이 통계
    python scripts/dedupe_registry.py --domain Img            # Img 만
    python scripts/dedupe_registry.py --remove-staged-files   # 물리 staged 파일도 제거
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMBEDDED_DB = ROOT / "Data" / "embedded_DB"
RAW_DB = ROOT / "Data" / "raw_DB"
# 실제 ChromaDB 경로는 PATHS["TRICHEF_CHROMA"] = embedded_DB/trichef.
# (트리 안에 trichef_chroma 폴더는 별도 — 사용 안 함)
CHROMA_DIR = EMBEDDED_DB / "trichef"

# 도메인별 설정.
# - cache_dir: registry.json + .npy 위치
# - npy_files: 3축 .npy 파일들 (행 단위로 필터)
# - ids_file: ids.json (key 순서가 .npy 행 순서와 매칭)
# - chroma_collection: ChromaDB 컬렉션 이름
# - raw_subdir: raw_DB 하위 (staged 파일 정리용)
DOMAIN_CFG = {
    "Img": {
        "cache_dir": EMBEDDED_DB / "Img",
        "npy_files": ["cache_img_Re_siglip2.npy",
                      "cache_img_Im_e5cap.npy",
                      "cache_img_Z_dinov2.npy"],
        "ids_file":  "img_ids.json",
        "chroma_collection": "trichef_image",
        "raw_subdir": RAW_DB / "Img",
    },
    "Doc": {
        "cache_dir": EMBEDDED_DB / "Doc",
        "npy_files": ["cache_doc_page_Re.npy",
                      "cache_doc_page_Im.npy",
                      "cache_doc_page_Z.npy"],
        "ids_file":  "doc_page_ids.json",
        "chroma_collection": "trichef_doc_page",
        "raw_subdir": RAW_DB / "Doc",
    },
    # AV 도메인은 .npy 가 segment 단위(파일 단위 아님)이므로 행 필터 안 함.
    # registry / ChromaDB 만 dedup. AV ChromaDB collection 은 별도 디렉토리 사용.
    "Movie": {
        "cache_dir": EMBEDDED_DB / "Movie",
        "npy_files": [],   # segment-level npy, file-level dedup 시 행수 안 맞음
        "ids_file":  "movie_ids.json",
        "chroma_collection": None,   # Movie 는 trichef ChromaDB 미사용
        "raw_subdir": RAW_DB / "Movie",
        "av": True,
    },
    "Rec": {
        "cache_dir": EMBEDDED_DB / "Rec",
        "npy_files": [],
        "ids_file":  "music_ids.json",
        "chroma_collection": None,
        "raw_subdir": RAW_DB / "Rec",
        "av": True,
    },
}


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    bak = path.with_suffix(path.suffix + f".bak.{int(time.time())}")
    shutil.copy2(path, bak)
    return bak


def _decide_keep(keys: list[str], registry: dict) -> str:
    """중복 그룹에서 살릴 key 결정.

    우선순위:
      1. non-staged (canonical raw_DB sub-path) — 기존 임베딩 일관성
      2. 그 중 abs path 가 disk 에 실제 존재하는 것
      3. abs 미존재 시 staged 중 첫 번째
    """
    non_staged = [k for k in keys if not k.startswith("staged/")]
    if non_staged:
        # disk 존재 여부 우선
        for k in non_staged:
            abs_p = registry[k].get("abs") if isinstance(registry[k], dict) else None
            if abs_p and Path(abs_p).is_file():
                return k
        return non_staged[0]
    return keys[0]


def _decide_keep_av(keys: list[str], registry: dict) -> str:
    """AV 도메인 dedup keep 결정.

    우선순위:
      1. relative form (raw_DB/<domain>/ prefix 없는 키)
      2. raw_DB 이후 sub-path (예: '훤_youtube_2차/file.mp4')
      3. 그 외 첫 번째
    """
    rel = [k for k in keys if not (k.startswith("C:") or k.startswith("/")
                                   or "\\" in k[:5])]
    if rel:
        return rel[0]
    return keys[0]


def dedupe_domain(domain: str, dry_run: bool = False,
                  remove_staged_files: bool = False) -> dict:
    cfg = DOMAIN_CFG[domain]
    cache_dir = cfg["cache_dir"]
    reg_path = cache_dir / "registry.json"
    if not reg_path.exists():
        return {"domain": domain, "skipped": True, "reason": "registry.json 없음"}

    registry = json.loads(reg_path.read_text(encoding="utf-8"))
    n_before = len(registry)
    is_av = bool(cfg.get("av"))

    # SHA 그룹화
    by_sha: dict[str, list[str]] = defaultdict(list)
    no_sha_keys: list[str] = []
    for key, entry in registry.items():
        sha = entry.get("sha") if isinstance(entry, dict) else None
        if not sha:
            no_sha_keys.append(key)
            continue
        by_sha[sha].append(key)

    # keep / remove 결정
    keys_to_keep: set[str] = set(no_sha_keys)
    keys_to_remove: set[str] = set()
    decide_fn = _decide_keep_av if is_av else _decide_keep
    for sha, keys in by_sha.items():
        if len(keys) == 1:
            keys_to_keep.add(keys[0])
        else:
            keep = decide_fn(keys, registry)
            keys_to_keep.add(keep)
            for k in keys:
                if k != keep:
                    keys_to_remove.add(k)

    n_after = len(keys_to_keep)
    n_removed = len(keys_to_remove)

    print(f"\n=== {domain} ===")
    print(f"  registry entries:   {n_before}")
    print(f"  unique SHA groups:  {len(by_sha)}")
    print(f"  no_sha entries:     {len(no_sha_keys)} (keep)")
    print(f"  duplicate groups:   {sum(1 for k in by_sha.values() if len(k) > 1)}")
    print(f"  to keep:            {n_after}")
    print(f"  to remove:          {n_removed}")

    if dry_run:
        print("  (dry-run: 변경 없음)")
        return {"domain": domain, "before": n_before, "after": n_after,
                "removed": n_removed, "dry_run": True}

    if n_removed == 0:
        print("  변경 없음.")
        return {"domain": domain, "before": n_before, "after": n_after, "removed": 0}

    # 1. registry 백업 + 갱신
    bak = _backup(reg_path)
    print(f"  backup: {bak.name if bak else 'X'}")
    new_registry = {k: v for k, v in registry.items() if k in keys_to_keep}
    reg_path.write_text(json.dumps(new_registry, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # ── AV 전용: segments.json + .npy + ids.json 동기 필터 ──
    # AV 의 .npy 는 segment 단위 (수만 행), keep_mask 는 file_path 기준으로 빌드.
    # 같은 SHA·basename 의 abs-form 과 rel-form segments 가 모두 등록되어 있어
    # 절반이 중복. abs-form file_path 의 segments 모두 제거.
    if is_av:
        try:
            import numpy as np
            segs_path = cache_dir / "segments.json"
            ids_path  = cache_dir / cfg["ids_file"]
            if not segs_path.exists() or not ids_path.exists():
                print("  ⚠️  AV segments.json/ids.json 없음 — segment 필터 skip")
            else:
                segs = json.loads(segs_path.read_text(encoding="utf-8"))
                ids_data = json.loads(ids_path.read_text(encoding="utf-8"))
                ids = ids_data.get("ids", []) if isinstance(ids_data, dict) else ids_data
                n_total = len(ids)
                if len(segs) != n_total:
                    print(f"  ⚠️  segments({len(segs)}) != ids({n_total}) — abort AV filter")
                else:
                    # keep mask: segment.file 가 keys_to_keep 에 있는지
                    keep_mask = []
                    for s in segs:
                        fp = s.get("file") or s.get("file_path") or ""
                        # registry key 형식과 정확히 일치하는지
                        keep_mask.append(fp in keys_to_keep)
                    n_keep = sum(keep_mask)
                    n_drop = n_total - n_keep
                    print(f"  AV segment 필터: total={n_total}, keep={n_keep}, drop={n_drop}")

                    # backup + filter
                    _backup(segs_path)
                    new_segs = [segs[i] for i in range(n_total) if keep_mask[i]]
                    segs_path.write_text(
                        json.dumps(new_segs, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

                    # ids.json filter
                    _backup(ids_path)
                    new_ids = [ids[i] for i in range(n_total) if keep_mask[i]]
                    ids_payload = {"ids": new_ids} if isinstance(ids_data, dict) else new_ids
                    ids_path.write_text(
                        json.dumps(ids_payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

                    # .npy filter — AV 도메인의 모든 cache_*.npy
                    mask_arr = np.array(keep_mask)
                    for npy_path in cache_dir.glob("cache_*.npy"):
                        if npy_path.suffix == ".bak":
                            continue
                        try:
                            arr = np.load(npy_path)
                            if arr.shape[0] != n_total:
                                print(f"  ⚠️  {npy_path.name}: 행수 {arr.shape[0]} != "
                                      f"ids {n_total} — skip")
                                continue
                            _backup(npy_path)
                            np.save(npy_path, arr[mask_arr])
                            print(f"  {npy_path.name}: {n_total} → {n_keep}")
                        except Exception as ne:
                            print(f"  ⚠️  {npy_path.name} 필터 실패: {ne}")

                    # token_sets.json 도 동기 필터
                    for ts_name in (f"{cfg['ids_file'].split('_')[0]}_token_sets.json",
                                    "token_sets.json"):
                        ts_path = cache_dir / ts_name
                        if not ts_path.exists():
                            continue
                        try:
                            ts = json.loads(ts_path.read_text(encoding="utf-8"))
                            if isinstance(ts, list) and len(ts) == n_total:
                                _backup(ts_path)
                                new_ts = [ts[i] for i in range(n_total) if keep_mask[i]]
                                ts_path.write_text(
                                    json.dumps(new_ts, ensure_ascii=False, indent=2),
                                    encoding="utf-8",
                                )
                                print(f"  {ts_name}: {n_total} → {n_keep}")
                        except Exception as te:
                            print(f"  ⚠️  {ts_name} 필터 실패: {te}")
        except Exception as e:
            print(f"  ⚠️  AV segment 필터 실패: {e}")

    # 2. ids.json + .npy 동기 필터 (file-level: Doc/Img)
    ids_path = cache_dir / cfg["ids_file"]
    if not is_av and ids_path.exists():
        try:
            import numpy as np
            ids_data = json.loads(ids_path.read_text(encoding="utf-8"))
            ids = ids_data.get("ids", []) if isinstance(ids_data, dict) else ids_data
            keep_mask = [(k in keys_to_keep) for k in ids]
            n_keep = sum(keep_mask)
            n_total = len(ids)

            # .npy 행 필터
            for fn in cfg["npy_files"]:
                npy_path = cache_dir / fn
                if not npy_path.exists():
                    continue
                arr = np.load(npy_path)
                if arr.shape[0] != n_total:
                    print(f"  ⚠️  {fn}: 행수 {arr.shape[0]} != ids {n_total} — skip")
                    continue
                _backup(npy_path)
                np.save(npy_path, arr[np.array(keep_mask)])
                print(f"  {fn}: {n_total} → {n_keep}")

            # ids.json 갱신
            new_ids = [ids[i] for i in range(n_total) if keep_mask[i]]
            _backup(ids_path)
            ids_payload = {"ids": new_ids} if isinstance(ids_data, dict) else new_ids
            ids_path.write_text(json.dumps(ids_payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
            print(f"  ids.json: {n_total} → {n_keep}")
        except Exception as e:
            print(f"  ⚠️  .npy/ids 필터 실패: {e}")

    # 3. ChromaDB 정리 (Movie/Rec 는 trichef ChromaDB 미사용 → skip)
    if not cfg.get("chroma_collection"):
        print(f"  ChromaDB: collection 없음 - skip")
        return {"domain": domain, "before": n_before, "after": n_after,
                "removed": n_removed, "dry_run": False}
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
        all_ids = col.get()["ids"]
        to_delete = [i for i in all_ids if i in keys_to_remove]
        if to_delete:
            CHUNK = 5000
            for i in range(0, len(to_delete), CHUNK):
                col.delete(ids=to_delete[i:i + CHUNK])
            print(f"  ChromaDB: {len(to_delete)} entries 제거")
        else:
            print(f"  ChromaDB: 제거할 entry 없음")
    except Exception as e:
        print(f"  ⚠️  ChromaDB 정리 실패: {e}")

    # 4. (선택) 물리 staged 파일 제거
    if remove_staged_files:
        staged_to_remove = [k for k in keys_to_remove if k.startswith("staged/")]
        removed_files = 0
        for k in staged_to_remove:
            entry = registry.get(k, {})
            staged_path = entry.get("staged") if isinstance(entry, dict) else None
            if not staged_path:
                # 추정: raw_DB/<domain>/<key>
                staged_path = str(cfg["raw_subdir"] / k)
            try:
                p = Path(staged_path)
                if p.is_file():
                    p.unlink()
                    removed_files += 1
            except Exception:
                pass
        print(f"  staged 물리 파일: {removed_files} 제거")

    return {"domain": domain, "before": n_before, "after": n_after,
            "removed": n_removed, "dry_run": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="registry 중복 정리")
    parser.add_argument("--domain", choices=list(DOMAIN_CFG.keys()),
                        help="단일 도메인만 (기본: 전체)")
    parser.add_argument("--dry-run", action="store_true",
                        help="변경 없이 카운트만 출력")
    parser.add_argument("--remove-staged-files", action="store_true",
                        help="물리 staged 파일도 제거")
    args = parser.parse_args()

    # 백엔드 활성 검사
    try:
        import socket
        s = socket.create_connection(("127.0.0.1", 5001), timeout=1)
        s.close()
        if not args.dry_run:
            print("⚠️  백엔드(127.0.0.1:5001) 가 실행 중입니다. 종료 후 다시 시도하세요.",
                  file=sys.stderr)
            return 2
    except Exception:
        pass  # 5001 미응답 = 백엔드 정지 = 진행 OK

    domains = [args.domain] if args.domain else list(DOMAIN_CFG.keys())
    print(f"중복 정리: {', '.join(domains)} ({'dry-run' if args.dry_run else 'apply'})")
    print(f"  embedded_DB: {EMBEDDED_DB}")

    results = [dedupe_domain(d, dry_run=args.dry_run,
                             remove_staged_files=args.remove_staged_files)
               for d in domains]

    print("\n" + "=" * 60)
    print("종합")
    print("=" * 60)
    for r in results:
        if r.get("skipped"):
            print(f"  {r['domain']}: 건너뜀 ({r.get('reason')})")
        else:
            print(f"  {r['domain']}: {r['before']} → {r['after']} "
                  f"(제거 {r['removed']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
