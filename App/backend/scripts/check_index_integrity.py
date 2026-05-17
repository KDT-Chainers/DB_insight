"""[D-3] 인덱스 무결성 스캐너.

모든 도메인(Img/Doc/Movie/Rec)의 캐시 파일 행 수 일치 여부를 검증.
엔진 reload 시 비활성화되는 채널(sparse/ASF/Im_body 등)을 사전 감지.

검사 항목:
  - ids JSON 길이
  - cache_*_Re/Im/Z .npy shape[0]
  - cache_*_sparse.npz shape[0]
  - asf_token_sets / token_sets JSON 길이
  - segments.json 길이 (AV 전용)
  - Doc Im / Im_body 일치

출력: 각 도메인별 표 + 불일치 경고. exit 0 (정상) / exit 1 (불일치 발견).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "App" / "backend"))
from config import PATHS  # noqa: E402

EMBEDDED_DB = Path(PATHS["DATA_ROOT"]) / "embedded_DB" \
    if "DATA_ROOT" in PATHS else _ROOT / "Data" / "embedded_DB"
if not EMBEDDED_DB.exists():
    EMBEDDED_DB = _ROOT / "Data" / "embedded_DB"


def _len_json_list_or_ids(p: Path) -> int | None:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            ids = d.get("ids")
            if isinstance(ids, list):
                return len(ids)
            return len(d)  # dict keys 수
        if isinstance(d, list):
            return len(d)
    except Exception:
        return None
    return None


def _npy_rows(p: Path) -> int | None:
    try:
        return int(np.load(p, mmap_mode="r").shape[0])
    except Exception:
        return None


def _npz_rows(p: Path) -> int | None:
    try:
        return int(sp.load_npz(p).shape[0])
    except Exception:
        return None


def check_domain(name: str, dir_path: Path, spec: dict) -> tuple[bool, list[str]]:
    """spec = {'label': filename or callable, ...}

    Returns (ok, issues). 도메인 캐시 자체가 없으면 (True, ['absent']) — 미설치
    상태로 간주, 무결성 위반 아님.
    """
    print(f"\n[{name}] {dir_path}")
    if not dir_path.exists():
        print("  -  도메인 디렉토리 없음 (미설치)")
        return True, ["absent"]
    rows = {}
    issues = []
    files_found = 0
    for label, fname in spec.items():
        p = dir_path / fname
        if not p.exists():
            print(f"  -  {label:<22s}  (파일 없음: {fname})")
            continue
        files_found += 1
        if fname.endswith(".json"):
            n = _len_json_list_or_ids(p)
        elif fname.endswith(".npy"):
            n = _npy_rows(p)
        elif fname.endswith(".npz"):
            n = _npz_rows(p)
        else:
            n = None
        rows[label] = n
        print(f"     {label:<22s}  {n}")

    if files_found == 0:
        print("  -  파일 없음 (미설치 또는 다른 구조)")
        return True, ["empty"]

    # 기준 = ids 길이 (가장 신뢰)
    baseline = rows.get("ids")
    if baseline is None:
        # ids 없지만 다른 파일 있음 → 별도 구조 가능성. 단순 보고만.
        print(f"  ?  ids 필드 없음 — 별도 구조 가능 (불일치 미판정)")
        return True, ["no_ids_field"]
    for label, n in rows.items():
        if n is not None and n != baseline:
            msg = f"{label}={n} ≠ ids={baseline}"
            issues.append(msg)
            print(f"  ✗ {msg}")
    if not issues:
        print(f"  ✓ 모두 정렬 ({baseline})")
    return len(issues) == 0, issues


def main():
    print(f"=== 인덱스 무결성 스캔 ===")
    print(f"  EMBEDDED_DB: {EMBEDDED_DB}")

    all_ok = True

    # Img
    ok, _ = check_domain("Img", EMBEDDED_DB / "Img", {
        "ids":      "img_ids.json",
        "Re":       "cache_img_Re_siglip2.npy",
        "Im":       "cache_img_Im_e5cap.npy",
        "Z":        "cache_img_Z_dinov2.npy",
        "sparse":   "cache_img_sparse.npz",
    })
    all_ok = all_ok and ok

    # Doc
    ok, _ = check_domain("Doc", EMBEDDED_DB / "Doc", {
        "ids":      "doc_page_ids.json",
        "Re":       "cache_doc_page_Re.npy",
        "Im":       "cache_doc_page_Im.npy",
        "Im_body":  "cache_doc_page_Im_body.npy",
        "Z":        "cache_doc_page_Z.npy",
        "sparse":   "cache_doc_page_sparse.npz",
        "asf":      "asf_token_sets.json",
    })
    all_ok = all_ok and ok

    # Movie
    ok, _ = check_domain("Movie", EMBEDDED_DB / "Movie", {
        "ids":      "movie_ids.json",
        "segments": "segments.json",
        "Re":       "cache_movie_Re.npy",
        "Im":       "cache_movie_Im.npy",
        "Z":        "cache_movie_Z.npy",
        "sparse":   "cache_movie_sparse.npz",
        "tokens":   "movie_token_sets.json",
    })
    all_ok = all_ok and ok

    # Rec (Audio)
    ok, _ = check_domain("Rec/Audio", EMBEDDED_DB / "Rec", {
        "ids":      "music_ids.json",
        "segments": "segments.json",
        "Re":       "cache_music_Re.npy",
        "Im":       "cache_music_Im.npy",
        "Z":        "cache_music_Z.npy",
        "sparse":   "cache_music_sparse.npz",
    })
    all_ok = all_ok and ok

    # BGM
    bgm_dir = EMBEDDED_DB / "BGM"
    if bgm_dir.exists():
        ok, _ = check_domain("BGM", bgm_dir, {
            "ids":     "bgm_ids.json",
            "audio":   "cache_bgm_audio.npy",
            "text":    "cache_bgm_text.npy",
        })
        all_ok = all_ok and ok

    print(f"\n=== 종합 : {'✓ 전부 정상' if all_ok else '✗ 불일치 발견'} ===")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
