"""scripts/check_index_integrity.py — 5도메인 인덱스 정합성 점검.

각 도메인의 Re/Im/Z npy, ids.json, segments.json, sparse.npz, asf_token_sets.json
파일 수·shape 일치 여부를 확인하고 JSON 결과를 bench_results/ 에 저장.

실행:
  python scripts/check_index_integrity.py
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

import numpy as np
try:
    from scipy import sparse as sp
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

DATA = ROOT / "Data" / "embedded_DB"

DOMAIN_SPECS: dict[str, dict] = {
    "Doc": {
        "label": "doc_page",
        "Re":     "cache_doc_page_Re.npy",
        "Im":     "cache_doc_page_Im.npy",
        "Z":      "cache_doc_page_Z.npy",
        "ids":    "doc_page_ids.json",
        "sparse": "cache_doc_page_sparse.npz",
        "asf":    "asf_token_sets.json",
        "Im_body": "cache_doc_page_Im_body.npy",
    },
    "Img": {
        "label": "image",
        "Re":    "cache_img_Re_siglip2.npy",
        "Im":    "cache_img_Im_e5cap.npy",
        "Z":     "cache_img_Z_dinov2.npy",
        "ids":   "img_ids.json",
        "sparse":"cache_img_sparse.npz",
        "asf":   "asf_token_sets.json",
        "Im_L1": "cache_img_Im_L1.npy",
        "Im_L2": "cache_img_Im_L2.npy",
        "Im_L3": "cache_img_Im_L3.npy",
    },
    "Movie": {
        "label":    "movie",
        "Re":       "cache_movie_Re.npy",
        "Im":       "cache_movie_Im.npy",
        "Z":        "cache_movie_Z.npy",
        "ids":      "movie_ids.json",
        "segments": "movie_segments.json",
        "sparse":   "cache_movie_sparse.npz",
        "asf":      "movie_token_sets.json",
    },
    "Rec": {
        "label":    "music",
        "Re":       "cache_music_Re.npy",
        "Im":       "cache_music_Im.npy",
        "Z":        "cache_music_Z.npy",
        "ids":      "music_ids.json",
        "segments": "music_segments.json",
        "sparse":   "cache_music_sparse.npz",
        "asf":      "music_token_sets.json",
    },
    "Bgm": {
        "label": "bgm",
        "index": "bgm_index.json",
        "clap":  "bgm_clap.npy",
    },
}


def _load_ids(path: Path) -> list:
    raw = json.loads(path.read_bytes().decode("utf-8", errors="replace"))
    if isinstance(raw, dict):
        return raw.get("ids", [])
    return list(raw)


def check_domain(folder_name: str, spec: dict, base: Path) -> dict:
    d = base / folder_name
    label = spec["label"]
    result: dict = {"domain": label, "folder": folder_name, "ok": True, "warnings": [], "info": {}}

    def warn(msg: str):
        result["warnings"].append(msg)
        result["ok"] = False

    def info(msg: str):
        result["info"][msg.split("=")[0].strip()] = msg

    # BGM 는 별도 체계
    if label == "bgm":
        for key in ("index", "clap"):
            fn = spec.get(key)
            if not fn:
                continue
            fp = d / fn
            if not fp.exists():
                warn(f"{fn} 없음")
            else:
                if fn.endswith(".npy"):
                    arr = np.load(fp)
                    info(f"{key} shape = {arr.shape}")
                    result["info"][f"{key}_shape"] = list(arr.shape)
                else:
                    try:
                        idx = json.loads(fp.read_bytes())
                        cnt = len(idx) if isinstance(idx, list) else len(idx.get("items", []))
                        info(f"{key} items = {cnt}")
                        result["info"][f"{key}_count"] = cnt
                    except Exception as e:
                        warn(f"{fn} 파싱 오류: {e}")
        return result

    # Re 기준 행 수 확인
    re_fn = spec.get("Re")
    if not re_fn or not (d / re_fn).exists():
        warn(f"Re 파일 없음 ({re_fn}) — 인덱싱 미완료")
        return result

    Re = np.load(d / re_fn)
    N = Re.shape[0]
    result["info"]["N"] = N
    result["info"]["Re_shape"] = list(Re.shape)
    print(f"  Re {Re.shape}", end="")

    # Im
    im_fn = spec.get("Im")
    if im_fn and (d / im_fn).exists():
        Im = np.load(d / im_fn)
        result["info"]["Im_shape"] = list(Im.shape)
        if Im.shape[0] != N:
            warn(f"Im 행 수 {Im.shape[0]} ≠ Re {N}")
        print(f"  Im {Im.shape}", end="")
    else:
        warn(f"Im 파일 없음 ({im_fn})")

    # Z
    z_fn = spec.get("Z")
    if z_fn and (d / z_fn).exists():
        Z = np.load(d / z_fn)
        result["info"]["Z_shape"] = list(Z.shape)
        if Z.shape[0] != N:
            warn(f"Z 행 수 {Z.shape[0]} ≠ Re {N}")
        print(f"  Z {Z.shape}", end="")
    else:
        result["info"]["Z_missing"] = True

    # ids
    ids_fn = spec.get("ids")
    if ids_fn and (d / ids_fn).exists():
        ids = _load_ids(d / ids_fn)
        result["info"]["ids_count"] = len(ids)
        if len(ids) != N:
            warn(f"ids 수 {len(ids)} ≠ Re {N}")
        print(f"  ids {len(ids)}", end="")
    else:
        warn(f"ids 파일 없음 ({ids_fn})")

    # segments (AV only)
    seg_fn = spec.get("segments")
    if seg_fn:
        seg_path = d / seg_fn
        if not seg_path.exists():
            # fallback
            seg_path = d / "segments.json"
        if seg_path.exists():
            segs = json.loads(seg_path.read_bytes().decode("utf-8", errors="replace"))
            result["info"]["segments_count"] = len(segs)
            if len(segs) != N:
                warn(f"segments 수 {len(segs)} ≠ Re {N}")
            print(f"  segs {len(segs)}", end="")

            # STT 텍스트 비율
            has_stt = sum(1 for s in segs if s.get("stt_text", "").strip())
            result["info"]["stt_coverage_pct"] = round(has_stt / max(len(segs), 1) * 100, 1)
            if has_stt / max(len(segs), 1) < 0.5:
                warn(f"STT 텍스트 coverage {result['info']['stt_coverage_pct']}% < 50%")
        else:
            warn(f"segments 파일 없음 ({seg_fn})")

    # sparse
    sp_fn = spec.get("sparse")
    if sp_fn and (d / sp_fn).exists() and _HAS_SCIPY:
        mat = sp.load_npz(d / sp_fn)
        result["info"]["sparse_shape"] = list(mat.shape)
        result["info"]["sparse_nnz"] = int(mat.nnz)
        if mat.shape[0] != N:
            warn(f"sparse 행 수 {mat.shape[0]} ≠ Re {N}")
        if mat.nnz == 0:
            warn("sparse nnz=0 — lexical 인덱스 비어 있음 (rebuild_*_lexical 재실행 필요)")
        print(f"  sparse {mat.shape} nnz={mat.nnz}", end="")

    # ASF token sets
    asf_fn = spec.get("asf")
    if asf_fn and (d / asf_fn).exists():
        sets = json.loads((d / asf_fn).read_bytes().decode("utf-8", errors="replace"))
        result["info"]["asf_sets_count"] = len(sets)
        if len(sets) != N:
            warn(f"asf_sets 수 {len(sets)} ≠ Re {N}")
        avg_toks = sum(len(s) for s in sets) / max(len(sets), 1)
        result["info"]["asf_avg_tokens"] = round(avg_toks, 1)
        if avg_toks < 2:
            warn(f"ASF 평균 토큰 수 {avg_toks:.1f} 너무 적음 — rebuild_asf_vocab 재실행 권장")

    # 이미지 전용: L1/L2/L3 캡션 fusion 상태
    for lv in ("Im_L1", "Im_L2", "Im_L3"):
        fn = spec.get(lv)
        if fn:
            fp = d / fn
            result["info"][f"{lv}_exists"] = fp.exists()

    # Doc 전용: Im_body fusion 상태
    body_fn = spec.get("Im_body")
    if body_fn:
        fp = d / body_fn
        result["info"]["Im_body_exists"] = fp.exists()
        if fp.exists():
            Ib = np.load(fp)
            result["info"]["Im_body_shape"] = list(Ib.shape)
            if Ib.shape[0] != N:
                warn(f"Im_body 행 수 {Ib.shape[0]} ≠ Re {N}")

    print()  # newline
    return result


def main() -> int:
    print("=" * 60)
    print("  DB_insight 인덱스 정합성 점검")
    print("=" * 60)

    report: dict = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "domains": {},
        "summary": {"ok": 0, "warn": 0},
    }

    for folder, spec in DOMAIN_SPECS.items():
        label = spec["label"]
        print(f"\n[{label}]  ({DATA / folder})")
        r = check_domain(folder, spec, DATA)
        report["domains"][label] = r
        status = "✓" if r["ok"] else "⚠"
        print(f"  → {status}  N={r['info'].get('N','?')}", end="")
        if r["warnings"]:
            for w in r["warnings"]:
                print(f"\n     ⚠ {w}", end="")
        print()
        if r["ok"]:
            report["summary"]["ok"] += 1
        else:
            report["summary"]["warn"] += 1

    # 추가: DOC_IM_ALPHA fusion 활성 여부 요약
    doc_info = report["domains"].get("doc_page", {}).get("info", {})
    img_info = report["domains"].get("image",    {}).get("info", {})
    print("\n[Fusion 활성화 요약]")
    print(f"  Doc Im_body fusion: {'✓ 활성' if doc_info.get('Im_body_exists') else '✗ 비활성'}")
    l_all = all(img_info.get(f"Im_{lv}_exists") for lv in ("L1", "L2", "L3"))
    print(f"  Img L1/L2/L3 3단계 캡션 fusion: {'✓ 활성' if l_all else '✗ 비활성'}")

    s = report["summary"]
    print(f"\n{'=' * 60}")
    print(f"결과: ✓ OK={s['ok']}  ⚠ WARN={s['warn']}")
    print(f"{'=' * 60}")

    out_dir = ROOT / "bench_results"
    out_dir.mkdir(exist_ok=True)
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"{ts}_check_index_integrity.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[saved] {out}")
    return 0 if s["warn"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
