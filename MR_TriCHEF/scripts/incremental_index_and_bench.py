"""incremental_index_and_bench.py -- 파일 1개씩 인덱싱 + calibration + bench 반복.

훤_youtube_1차 5개를 기준점(baseline)으로 삼고,
훤_youtube_2차 파일을 하나씩 추가하면서:
  1. 인덱싱 (movie_runner 단일 파일)
  2. Crossmodal calibration 재실행
  3. 테스트 쿼리 5개 confidence 측정
  4. JSON 누적 저장 + 4-panel 시각화 갱신

실행:
    python MR_TriCHEF/scripts/incremental_index_and_bench.py
    python MR_TriCHEF/scripts/incremental_index_and_bench.py --max 10   # 최대 10개
    python MR_TriCHEF/scripts/incremental_index_and_bench.py --dry-run  # 인덱싱 없이 현황만
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "MR_TriCHEF"))

from pipeline.paths import (
    MOVIE_RAW_DIR, MOVIE_CACHE_DIR, MOVIE_EXTS,
)
from pipeline import registry as reg_mod
from pipeline import cache as cache_mod
from pipeline.calibration import calibrate_crossmodal_movie, CAL_PATH

RESULTS_DIR = _root / "MR_TriCHEF" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
BENCH_JSON  = RESULTS_DIR / "incremental_movie_2cha.json"

# 훤_youtube_1차 = baseline (이미 인덱싱됨)
BASELINE_DIR = MOVIE_RAW_DIR / "훤_youtube_1차"
TARGET_DIR   = MOVIE_RAW_DIR / "훤_youtube_2차"

TEST_QUERIES = [
    "농구 덩크 경기",
    "경제 투자 주식",
    "뉴스 정치 사회",
    "물리 과학 실험",
    "게임 플레이 스트리밍",
]

NULL_QUERIES_SHORT = [
    "날씨가 맑다", "자동차 엔진 수리", "요리 레시피",
    "강아지 산책", "주식 시장 분석",
    "커피 로스팅", "바다 서핑", "컴퓨터 조립",
    "정원 식물", "비행기 출국",
]


# ── 유틸 ──────────────────────────────────────────────────────────

def hermitian_score_vec(q_Re, q_Im, d_Re, d_Im, alpha=0.4):
    A = d_Re @ q_Re
    B = d_Im @ q_Im
    return np.sqrt(A**2 + (alpha * B)**2)


def load_cache():
    Re = np.load(MOVIE_CACHE_DIR / "cache_movie_Re.npy")
    Im = np.load(MOVIE_CACHE_DIR / "cache_movie_Im.npy")
    ids_raw = json.loads((MOVIE_CACHE_DIR / "movie_ids.json").read_text("utf-8"))
    ids = ids_raw if isinstance(ids_raw, list) else ids_raw.get("ids", [])
    return Re, Im, ids


def indexed_files() -> set[str]:
    reg = reg_mod.load(MOVIE_CACHE_DIR / "registry.json")
    return set(reg.keys())


def pending_files() -> list[Path]:
    """훤_youtube_2차 에서 아직 인덱싱되지 않은 파일 목록 (정렬)."""
    done = indexed_files()
    result = []
    for p in sorted(TARGET_DIR.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in MOVIE_EXTS:
            continue
        rel = str(p.relative_to(MOVIE_RAW_DIR)).replace("\\", "/")
        if rel not in done:
            result.append(p)
    return result


def run_calibration(encoders: dict) -> dict:
    return calibrate_crossmodal_movie(MOVIE_CACHE_DIR, encoders,
                                      sample_q=20, pairs_per_q=15)


def run_bench_queries(encoders, cal: dict) -> dict:
    Re, Im, ids = load_cache()
    bge = encoders["bge"]
    sig = encoders["sig"]

    mu  = cal.get("mu_null", 0.0)
    sig_val = cal.get("sigma_null", 1.0)

    file_idx: dict[str, list[int]] = {}
    for i, rel in enumerate(ids):
        file_idx.setdefault(rel, []).append(i)

    results: dict[str, dict] = {}
    for q in TEST_QUERIES:
        q_Re = sig.embed_texts([q])[0]
        q_Im = bge.embed([q])[0]
        per_seg = hermitian_score_vec(q_Re, q_Im, Re, Im)

        # 파일별 top-3 평균
        best = 0.0
        for rel, idxs in file_idx.items():
            segs = sorted([float(per_seg[i]) for i in idxs], reverse=True)
            agg = float(np.mean(segs[:3]))
            if agg > best:
                best = agg

        z = (best - mu) / max(sig_val, 1e-9)
        conf = 1.0 / (1.0 + math.exp(-z / 2.0))
        results[q] = {"raw": round(best, 4), "conf": round(conf, 4)}

    return results


def index_one_file(vid: Path) -> dict:
    """지정된 단일 파일만 인덱싱 (stage-sequential VRAM 안전).

    movie_runner 의 파이프라인을 직접 재현하되, 하나의 파일만 처리.
    정혜_BGM_1차 등 다른 폴더 파일이 끼어드는 문제를 방지.
    """
    import gc, shutil, tempfile
    from pipeline import cache as _cache, registry as _reg
    from pipeline.frame_sampler import extract_audio, extract_frames, probe_duration
    from pipeline.stt import WhisperSTT
    from pipeline.text import BGEM3Encoder
    from pipeline.vision import DINOv2Encoder, SigLIP2Encoder
    from pipeline.movie_runner import _align_stt_to_frames

    reg_path = MOVIE_CACHE_DIR / "registry.json"
    reg      = _reg.load(reg_path)
    rel = str(vid.relative_to(MOVIE_RAW_DIR)).replace("\\", "/")

    # SHA 증분 체크
    sha = _reg.sha256(vid)
    if reg.get(rel, {}).get("sha") == sha:
        return {"status": "skipped", "frames": 0, "duration": 0,
                "elapsed": 0, "reason": "sha match"}

    tmp = Path(tempfile.mkdtemp(prefix="mmtri_single_"))
    t0  = time.time()
    try:
        frames = extract_frames(vid, tmp / "frames", fps=0.5, scene_thresh=0.2)
        if not frames:
            return {"status": "error", "reason": "no frames"}
        wav = extract_audio(vid, tmp / "audio.wav")
        dur = probe_duration(vid)
        frame_paths = [f.path for f in frames]

        sig = SigLIP2Encoder()
        Re  = sig.embed_images(frame_paths, batch=8)
        sig.unload(); del sig; gc.collect()

        dino = DINOv2Encoder()
        Z    = dino.embed_images(frame_paths, batch=8)
        dino.unload(); del dino; gc.collect()

        stt      = WhisperSTT()
        stt_segs = stt.transcribe(wav, language=None)
        stt.unload(); del stt; gc.collect()

        frame_times    = [(f.t_start, f.t_end) for f in frames]
        frame_stt_text = _align_stt_to_frames(stt_segs, frame_times)
        bge = BGEM3Encoder()
        Im  = bge.embed([t if t else " " for t in frame_stt_text], batch=16)
        bge.unload(); del bge; gc.collect()

        _cache.append_npy(MOVIE_CACHE_DIR / "cache_movie_Re.npy", Re)
        _cache.append_npy(MOVIE_CACHE_DIR / "cache_movie_Im.npy", Im)
        _cache.append_npy(MOVIE_CACHE_DIR / "cache_movie_Z.npy",  Z)
        _cache.append_ids(MOVIE_CACHE_DIR / "movie_ids.json", [rel] * len(frames))

        seg_meta = [
            {"file": rel, "file_name": vid.name,
             "frame_idx": i, "t_start": f.t_start, "t_end": f.t_end,
             "stt_text": frame_stt_text[i]}
            for i, f in enumerate(frames)
        ]
        _cache.append_segments(MOVIE_CACHE_DIR / "segments.json", seg_meta)

        reg[rel] = {"sha": sha, "frames": len(frames), "duration": dur}
        _reg.save(reg_path, reg)

        el = round(time.time() - t0, 1)
        print(f"  done — frames={len(frames)} duration={dur:.1f}s elapsed={el}s")
        return {"status": "done", "frames": len(frames),
                "duration": dur, "elapsed": el, "reason": ""}

    except Exception as e:
        import traceback
        print(f"  ERROR: {e}\n{traceback.format_exc()[:500]}")
        return {"status": "error", "frames": 0, "duration": 0,
                "elapsed": round(time.time()-t0,1), "reason": str(e)[:200]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── 메인 ─────────────────────────────────────────────────────────

def main(max_files: int = 999, dry_run: bool = False):
    pending = pending_files()
    done_set = indexed_files()
    baseline = [k for k in done_set
                if k.startswith("훤_youtube_1차/") or
                   not k.startswith("훤_youtube_2차/")]

    print(f"[incremental] 기준 파일(1차): {len(baseline)}개  "
          f"대기(2차): {len(pending)}개  max={max_files}")

    if dry_run:
        print("[dry-run] 인덱싱 없이 현황만 출력")
        for i, p in enumerate(pending[:max_files]):
            print(f"  {i+1:3d}. {p.name}")
        return 0

    import gc
    import torch

    def _load_encoders():
        from pipeline.text import BGEM3Encoder
        from pipeline.vision import SigLIP2Encoder
        print("  [encoders] BGE-M3 + SigLIP2 로드...")
        return {"bge": BGEM3Encoder(), "sig": SigLIP2Encoder()}

    def _unload_encoders(enc):
        enc["bge"].unload(); enc["sig"].unload()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print("  [encoders] 언로드 완료")

    # 기존 결과 로드
    records: list[dict] = []
    if BENCH_JSON.exists():
        records = json.loads(BENCH_JSON.read_text("utf-8")).get("records", [])
        print(f"  기존 {len(records)}개 레코드 로드")

    # 기준점(N=baseline) 측정 (첫 실행 시만)
    if not records:
        print("\n[baseline] 1차 5개 기준점 측정...")
        encoders = _load_encoders()
        try:
            cal   = run_calibration(encoders)
            q_res = run_bench_queries(encoders, cal)
        finally:
            _unload_encoders(encoders)
        Re, Im, ids = load_cache()
        rec = {
            "n_total":    len(set(ids)),
            "n_segs":     len(ids),
            "source":     "훤_youtube_1차 (baseline)",
            "cal":        cal,
            "queries":    q_res,
            "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        records.append(rec)
        _save_and_plot(records)
        _print_rec(rec)

    processed = 0
    for vid in pending[:max_files]:
        rel = str(vid.relative_to(MOVIE_RAW_DIR)).replace("\\", "/")
        print(f"\n{'='*60}")
        print(f"[{processed+1}/{min(len(pending), max_files)}] {vid.name}")

        # STEP 1: 인덱싱 (movie_runner 내부에서 모델 로드/언로드)
        t0 = time.time()
        idx_res = index_one_file(vid)
        print(f"  인덱싱 결과: {idx_res}")

        if idx_res["status"] not in ("done", "skipped"):
            print(f"  SKIP (오류: {idx_res.get('reason', '')})")
            continue

        # STEP 2: 인덱싱 후 calibration + bench (별도 인코더 로드)
        encoders = _load_encoders()
        try:
            cal   = run_calibration(encoders)
            q_res = run_bench_queries(encoders, cal)
        finally:
            _unload_encoders(encoders)

        Re, Im, ids = load_cache()
        rec = {
            "n_total":       len(set(ids)),
            "n_segs":        len(ids),
            "source":        rel,
            "cal":           cal,
            "queries":       q_res,
            "indexed_at":    time.strftime("%Y-%m-%dT%H:%M:%S"),
            "index_elapsed": round(time.time() - t0, 1),
        }
        records.append(rec)
        _save_and_plot(records)
        _print_rec(rec)
        processed += 1

    print(f"\n[완료] {processed}개 처리, 결과: {BENCH_JSON}")
    return 0


def _print_rec(rec: dict):
    cal = rec["cal"]
    q   = rec["queries"]
    mean_conf = sum(v["conf"] for v in q.values()) / len(q)
    print(f"  N={rec['n_total']:3d} segs={rec['n_segs']:5d} "
          f"mu={cal.get('mu_null',0):.4f} "
          f"thr={cal.get('abs_threshold',0):.4f} "
          f"mean_conf={mean_conf:.3f}")
    for qtext, v in q.items():
        print(f"    {qtext[:20]:20s} raw={v['raw']:.4f}  conf={v['conf']:.3f}")


def _save_and_plot(records: list[dict]):
    BENCH_JSON.write_text(
        json.dumps({"records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _plot(records)


def _plot(records: list[dict]):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        for fn in ["Malgun Gothic", "Hancom Gothic", "Gulim"]:
            if any(f.name == fn for f in fm.fontManager.ttflist):
                plt.rcParams["font.family"] = fn
                plt.rcParams["axes.unicode_minus"] = False
                break
    except ImportError:
        return

    ns      = [r["n_total"] for r in records]
    mus     = [r["cal"].get("mu_null", 0) for r in records]
    thrs    = [r["cal"].get("abs_threshold", 0) for r in records]
    sigs    = [r["cal"].get("sigma_null", 0) for r in records]

    queries = list(records[0]["queries"].keys())
    conf_s  = {q: [r["queries"][q]["conf"] for r in records] for q in queries}
    raw_s   = {q: [r["queries"][q]["raw"]  for r in records] for q in queries}

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle("Movie Incremental Index — Calibration & Confidence Drift", fontsize=13)

    # Panel 1: calibration params
    ax = axes[0, 0]
    ax.plot(ns, mus,  "b-o", label="mu_null (crossmodal)")
    ax.plot(ns, sigs, "r-s", label="sigma_null")
    ax.plot(ns, thrs, "g-^", label="abs_threshold")
    ax.axvline(5, color="gray", linestyle="--", alpha=0.5, label="1차 기준점")
    ax.set_title("Calibration Parameters (crossmodal)")
    ax.set_xlabel("# total files indexed")
    ax.set_ylabel("score")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # Panel 2: confidence
    ax = axes[0, 1]
    for q, s in conf_s.items():
        ax.plot(ns, s, "-o", label=q[:12])
    ax.axhline(0.5, color="k", linestyle="--", alpha=0.4)
    ax.axvline(5, color="gray", linestyle="--", alpha=0.5)
    ax.set_title("Query Confidence (top-1 file)")
    ax.set_xlabel("# total files indexed")
    ax.set_ylabel("confidence")
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)

    # Panel 3: raw similarity
    ax = axes[1, 0]
    for q, s in raw_s.items():
        ax.plot(ns, s, "-o", label=q[:12])
    ax.axvline(5, color="gray", linestyle="--", alpha=0.5)
    ax.set_title("Raw Hermitian Score (top-1)")
    ax.set_xlabel("# total files indexed")
    ax.set_ylabel("hermitian score")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)

    # Panel 4: threshold margin
    ax = axes[1, 1]
    ax.set_title("Source Files Added (2차)")
    sources = [r["source"].split("/")[-1][:25] for r in records]
    mean_confs = [sum(v["conf"] for v in r["queries"].values()) / len(r["queries"])
                  for r in records]
    colors = ["steelblue" if "1차" in r["source"] else "tomato"
              for r in records]
    ax.bar(range(len(records)), mean_confs, color=colors, alpha=0.8)
    ax.set_xticks(range(len(records)))
    ax.set_xticklabels([s[:15] for s in sources], rotation=45, ha="right", fontsize=6)
    ax.set_ylabel("mean confidence")
    ax.set_title("Mean Confidence per Checkpoint (blue=1차, red=2차)")
    ax.axhline(0.5, color="k", linestyle="--", alpha=0.3)
    ax.grid(True, axis="y", alpha=0.3)

    plt.tight_layout()
    out = RESULTS_DIR / "incremental_movie_2cha.png"
    plt.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  [plot] {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=999,
                        help="최대 처리 파일 수 (기본: 전체)")
    parser.add_argument("--dry-run", action="store_true",
                        help="인덱싱 없이 대기 목록만 출력")
    args = parser.parse_args()
    sys.exit(main(max_files=args.max, dry_run=args.dry_run))
