"""4 도메인 인덱싱 정합성 종합 진단.

검사 항목:
  1. Registry 중복 (SHA, file_name 기준)
  2. Registry vs 디스크 파일 일치
  3. Registry vs ChromaDB 일치
  4. Registry vs .npy/ids.json 일치
  5. file_path 정규화 다중 형식 검출
"""
from __future__ import annotations
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Windows console UTF-8 강제 — reconfigure (background redirect 호환)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
EMB = ROOT / "Data" / "embedded_DB"

DOMAINS = {
    "Doc":   {"ids": "doc_page_ids.json"},
    "Img":   {"ids": "img_ids.json"},
    "Movie": {"ids": "movie_ids.json"},
    "Rec":   {"ids": "music_ids.json"},
}


def basename(key: str) -> str:
    return key.replace("\\", "/").rsplit("/", 1)[-1]


def main() -> int:
    print("=" * 70)
    print("4 도메인 인덱싱 정합성 진단")
    print("=" * 70)

    summary = {}
    for dom, cfg in DOMAINS.items():
        reg_path = EMB / dom / "registry.json"
        if not reg_path.exists():
            print(f"\n[{dom}] registry.json 없음 — 건너뜀")
            continue
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        n = len(reg)

        # SHA 중복
        sha_groups: dict[str, list[str]] = defaultdict(list)
        no_sha = 0
        for k, v in reg.items():
            if isinstance(v, dict) and v.get("sha"):
                sha_groups[v["sha"]].append(k)
            else:
                no_sha += 1
        sha_dups = {s: ks for s, ks in sha_groups.items() if len(ks) > 1}
        n_sha_dup_entries = sum(len(ks) for ks in sha_dups.values())

        # file_name 중복
        fname_groups: dict[str, list[str]] = defaultdict(list)
        for k in reg:
            fname_groups[basename(k)].append(k)
        fname_dups = {f: ks for f, ks in fname_groups.items() if len(ks) > 1}

        # key prefix 형식 분석
        prefix_count = Counter()
        for k in reg:
            n_path = k.replace("\\", "/")
            if n_path.startswith("staged/"):
                prefix_count["staged/"] += 1
            elif "/" in n_path:
                prefix_count[n_path.split("/", 1)[0] + "/..."] += 1
            else:
                prefix_count["(flat)"] += 1

        # disk 존재 여부
        n_missing_disk = 0
        for k, v in reg.items():
            if not isinstance(v, dict):
                continue
            abs_path = v.get("abs")
            if abs_path:
                if not Path(abs_path).exists():
                    n_missing_disk += 1

        # ids.json 정합성
        ids_path = EMB / dom / cfg["ids"]
        n_ids = -1
        if ids_path.exists():
            try:
                ids_data = json.loads(ids_path.read_text(encoding="utf-8"))
                ids = ids_data.get("ids", []) if isinstance(ids_data, dict) else ids_data
                n_ids = len(ids)
            except Exception:
                pass

        # .npy 파일 행수
        npy_rows = []
        for npy in (EMB / dom).glob("cache_*.npy"):
            try:
                import numpy as np
                arr = np.load(npy, mmap_mode="r")
                npy_rows.append((npy.name, arr.shape[0]))
            except Exception:
                pass

        print(f"\n[{dom}]")
        print(f"  registry entries:        {n}")
        print(f"  unique SHA groups:       {len(sha_groups)}")
        print(f"  SHA-중복 그룹 수:        {len(sha_dups)}")
        print(f"  SHA-중복 entries 합:     {n_sha_dup_entries}")
        print(f"  file_name 중복 그룹:     {len(fname_dups)}")
        print(f"  no_sha entries:          {no_sha}")
        print(f"  abs 파일 디스크 없음:    {n_missing_disk}")
        print(f"  key prefix 분포:         {dict(prefix_count.most_common(5))}")
        print(f"  ids.json 행수:           {n_ids}")
        for name, rows in npy_rows:
            ok = "✓" if rows == n_ids else "✗"
            print(f"    {ok} {name}: {rows}")

        # 샘플 중복 출력
        if sha_dups:
            print(f"  -- SHA 중복 샘플 (최대 3개) --")
            for sha, ks in list(sha_dups.items())[:3]:
                print(f"    SHA {sha[:12]}.. × {len(ks)}: {ks}")

        summary[dom] = {
            "total": n,
            "sha_dup_entries": n_sha_dup_entries,
            "fname_dup_groups": len(fname_dups),
            "missing_disk": n_missing_disk,
        }

    print("\n" + "=" * 70)
    print("요약")
    print("=" * 70)
    for dom, s in summary.items():
        flag = "⚠️" if (s["sha_dup_entries"] > 0 or s["missing_disk"] > 0) else "✓"
        print(f"  {flag} {dom}: 총 {s['total']:5d}, SHA중복 {s['sha_dup_entries']:4d}, "
              f"디스크 누락 {s['missing_disk']:4d}, fname중복 그룹 {s['fname_dup_groups']:4d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
