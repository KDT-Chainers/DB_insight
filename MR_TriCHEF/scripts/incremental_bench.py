"""incremental_bench.py -- 증분 인덱싱에 따른 calibration / 신뢰도 변화 시각화.

동작:
  전체 캐시(N_max 파일)에서 파일을 1개씩 추가하면서
    1. Null 분포 (mu_null, sigma_null, abs_threshold) 재측정
    2. 고정 테스트 쿼리 5개의 top-1 confidence 추적
    3. 결과를 matplotlib으로 4-panel 시각화

실행:
    python MR_TriCHEF/scripts/incremental_bench.py
    python MR_TriCHEF/scripts/incremental_bench.py --domain music
    python MR_TriCHEF/scripts/incremental_bench.py --domain movie --save results/
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "MR_TriCHEF"))

from pipeline.paths import (
    MOVIE_CACHE_DIR, MUSIC_CACHE_DIR,
    MOVIE_EXTS, MUSIC_EXTS,
)
from pipeline.text import BGEM3Encoder
from pipeline.vision import SigLIP2Encoder

# ── 하드코딩 파라미터 목록 (점검 대상) ────────────────────────────
HARDCODED_PARAMS = {
    "tri_gs.alpha":           0.4,     # Hermitian A² 가중치
    "tri_gs.beta":            0.2,     # Hermitian C² 가중치
    "frame_sampler.fps":      0.5,     # Movie 프레임 샘플링
    "frame_sampler.scene":    0.2,     # Scene change threshold
    "music.window_sec":       30.0,    # STT sliding window 크기
    "music.hop_sec":          15.0,    # Sliding window hop
    "search.top_agg_k":       3,       # 파일 내 top-k 집계
    "calibrate.conf_scale":   2.0,     # confidence = sigmoid(z / scale)
    "calibrate.fallback_mu":  0.25,    # null calibration 없을 때 fallback μ
    "calibrate.fallback_sig": 0.08,    # null calibration 없을 때 fallback σ
}

# ── 테스트 쿼리 ───────────────────────────────────────────────────
TEST_QUERIES = {
    "movie": [
        "농구 덩크 슛",
        "물리학 논쟁 토론",
        "기후 변화 온도 상승",
        "경제 위기 투자",
        "연예 시상식 수상",
    ],
    "music": [
        "학생 선생님 상담",
        "AI 창업 사업",
        "게임 플레이 전략",
        "뉴스 사회 이슈",
        "동물 고양이",
    ],
}

NULL_QUERIES = [
    "날씨가 맑다", "자동차 엔진 수리", "요리 레시피 김치찌개",
    "강아지 산책", "주식 시장 분석", "커피 원두 로스팅",
    "바다 서핑 파도", "컴퓨터 하드웨어 조립", "정원 가꾸기 식물",
    "비행기 공항 출국",
]


def hermitian_score(q_Re, q_Im, d_Re, d_Im,
                    alpha=0.4, beta=0.2):
    A = d_Re @ q_Re
    B = d_Im @ q_Im
    return np.sqrt(A**2 + (alpha * B)**2)


def load_cache(cache_dir: Path, kind: str):
    Re = np.load(cache_dir / f"cache_{kind}_Re.npy")
    Im = np.load(cache_dir / f"cache_{kind}_Im.npy")
    ids_raw = json.loads((cache_dir / f"{kind}_ids.json").read_text("utf-8"))
    ids = ids_raw if isinstance(ids_raw, list) else ids_raw.get("ids", [])
    segs = json.loads((cache_dir / "segments.json").read_text("utf-8"))
    return Re, Im, ids, segs


def ordered_files(ids: list[str]) -> list[str]:
    """중복 제거하면서 첫 등장 순서 유지."""
    seen: set[str] = set()
    result: list[str] = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result


def calibrate_null(Re_sub, Im_sub, alpha=0.4):
    """무작위 쌍 1000개로 null 분포 추정."""
    N = Re_sub.shape[0]
    if N < 2:
        return 0.0, 1e-6, 0.0
    rng = np.random.default_rng(42)
    pairs = min(1000, N * (N - 1) // 2)
    i_idx = rng.integers(0, N, pairs)
    j_idx = rng.integers(0, N, pairs)
    mask = i_idx != j_idx
    i_idx, j_idx = i_idx[mask], j_idx[mask]
    scores = hermitian_score(Re_sub[i_idx].T, Im_sub[i_idx].T,
                             Re_sub[j_idx],   Im_sub[j_idx], alpha=alpha)
    mu  = float(scores.mean())
    sig = float(scores.std()) + 1e-6
    # FAR=0.05 → Φ⁻¹(0.95) ≈ 1.645
    thr = mu + 1.645 * sig
    return mu, sig, thr


def query_confidence(q_vec_Re, q_vec_Im,
                     Re_sub, Im_sub, ids_sub,
                     mu, sig, alpha=0.4, top_k=3):
    """단일 쿼리 → 파일 단위 top-1 confidence."""
    per_seg = hermitian_score(q_vec_Re, q_vec_Im, Re_sub, Im_sub, alpha=alpha)

    file_idx: dict[str, list[int]] = {}
    for i, rel in enumerate(ids_sub):
        file_idx.setdefault(rel, []).append(i)

    best_score = 0.0
    for rel, idxs in file_idx.items():
        seg_scores = sorted([float(per_seg[i]) for i in idxs], reverse=True)
        agg = float(np.mean(seg_scores[:top_k]))
        if agg > best_score:
            best_score = agg

    z = (best_score - mu) / sig
    conf = 1.0 / (1.0 + math.exp(-z / 2.0))
    return best_score, conf


def run_incremental(domain: str = "movie") -> dict:
    """파일을 1개씩 추가하며 calibration + query confidence 기록."""
    cache_dir = MOVIE_CACHE_DIR if domain == "movie" else MUSIC_CACHE_DIR
    kind = domain

    print(f"[incremental_bench] domain={domain}  cache={cache_dir}")
    Re_all, Im_all, ids_all, _ = load_cache(cache_dir, kind)
    files = ordered_files(ids_all)
    N_max = len(files)
    print(f"  총 {N_max}개 파일, {len(ids_all)}개 세그먼트")

    # 쿼리 임베딩 (1회만 로드)
    print("  BGE-M3 로드 중...")
    bge = BGEM3Encoder()
    test_q_vecs = {q: bge.embed([q])[0] for q in TEST_QUERIES[domain]}
    null_q_vecs  = [bge.embed([q])[0] for q in NULL_QUERIES]

    sig_enc = None
    if domain == "movie":
        from pipeline.vision import SigLIP2Encoder
        print("  SigLIP2 로드 중...")
        sig_enc = SigLIP2Encoder()
        test_q_Re = {q: sig_enc.embed_texts([q])[0] for q in TEST_QUERIES[domain]}
        null_q_Re  = [sig_enc.embed_texts([q])[0] for q in NULL_QUERIES]
        sig_enc.unload(); del sig_enc

    bge.unload(); del bge

    records: list[dict] = []

    for n in range(1, N_max + 1):
        file_set = set(files[:n])
        row_mask = np.array([i for i, rel in enumerate(ids_all) if rel in file_set])

        Re_sub  = Re_all[row_mask]
        Im_sub  = Im_all[row_mask]
        ids_sub = [ids_all[i] for i in row_mask]

        # calibration
        mu, sig_val, thr = calibrate_null(Re_sub, Im_sub)

        # null 쿼리 평균 점수 (별도 추정)
        null_scores = []
        for qi, q_Im in enumerate(null_q_vecs):
            q_Re = null_q_Re[qi] if domain == "movie" else q_Im
            raw, _ = query_confidence(q_Re, q_Im, Re_sub, Im_sub, ids_sub,
                                      mu=mu, sig=sig_val)
            null_scores.append(raw)
        null_mean = float(np.mean(null_scores)) if null_scores else 0.0

        # test 쿼리 confidence
        q_confs = {}
        for q, q_Im in test_q_vecs.items():
            q_Re = test_q_Re[q] if domain == "movie" else q_Im
            raw, conf = query_confidence(q_Re, q_Im, Re_sub, Im_sub, ids_sub,
                                         mu=mu, sig=sig_val)
            q_confs[q] = {"raw": round(raw, 4), "conf": round(conf, 4)}

        rec = {
            "n_files": n,
            "n_segs":  len(row_mask),
            "mu_null": round(mu, 5),
            "sigma_null": round(sig_val, 5),
            "abs_threshold": round(thr, 5),
            "null_score_mean": round(null_mean, 5),
            "queries": q_confs,
        }
        records.append(rec)

        mean_conf = float(np.mean([v["conf"] for v in q_confs.values()]))
        print(f"  N={n:2d}  segs={len(row_mask):4d}  "
              f"mu={mu:.4f}  sig={sig_val:.4f}  thr={thr:.4f}  "
              f"null_mean={null_mean:.4f}  mean_conf={mean_conf:.3f}")

    return {"domain": domain, "records": records,
            "hardcoded_params": HARDCODED_PARAMS}


def plot_results(result: dict, save_dir: Path | None = None):
    try:
        import matplotlib
        matplotlib.use("Agg" if save_dir else "TkAgg")
        import matplotlib.pyplot as plt
        # Windows 한글 폰트 설정
        import matplotlib.font_manager as fm
        _kr_fonts = ["Malgun Gothic", "Hancom Gothic", "Gulim", "New Gulim"]
        for _fn in _kr_fonts:
            if any(f.name == _fn for f in fm.fontManager.ttflist):
                plt.rcParams["font.family"] = _fn
                plt.rcParams["axes.unicode_minus"] = False
                break
    except ImportError:
        print("[plot] matplotlib 없음 — JSON만 저장")
        return

    domain  = result["domain"]
    records = result["records"]
    ns      = [r["n_files"] for r in records]
    mus     = [r["mu_null"] for r in records]
    sigs    = [r["sigma_null"] for r in records]
    thrs    = [r["abs_threshold"] for r in records]
    nulls   = [r["null_score_mean"] for r in records]

    queries = list(records[0]["queries"].keys())
    conf_series = {
        q: [r["queries"][q]["conf"] for r in records]
        for q in queries
    }
    raw_series = {
        q: [r["queries"][q]["raw"] for r in records]
        for q in queries
    }

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle(f"Incremental Calibration Drift — domain: {domain}", fontsize=13)

    # Panel 1: mu_null / sigma_null / abs_threshold
    ax = axes[0, 0]
    ax.plot(ns, mus,  "b-o", label="mu_null")
    ax.plot(ns, sigs, "r-s", label="sigma_null")
    ax.plot(ns, thrs, "g-^", label="abs_threshold")
    ax.plot(ns, nulls,"k--x",label="null_score_mean")
    ax.set_title("Calibration Parameters")
    ax.set_xlabel("# files indexed")
    ax.set_ylabel("score")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(ns)

    # Panel 2: confidence 변화
    ax = axes[0, 1]
    for q, series in conf_series.items():
        ax.plot(ns, series, "-o", label=q[:15])
    ax.axhline(0.5, color="k", linestyle="--", alpha=0.4, label="conf=0.5")
    ax.set_title("Query Confidence (top-1)")
    ax.set_xlabel("# files indexed")
    ax.set_ylabel("confidence")
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(ns)

    # Panel 3: raw similarity 변화
    ax = axes[1, 0]
    for q, series in raw_series.items():
        ax.plot(ns, series, "-o", label=q[:15])
    ax.set_title("Raw Similarity Score (top-1 file)")
    ax.set_xlabel("# files indexed")
    ax.set_ylabel("hermitian score")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(ns)

    # Panel 4: threshold vs null_mean gap (판별 여유)
    ax = axes[1, 1]
    gap = [t - n for t, n in zip(thrs, nulls)]
    ax.bar(ns, gap, color="steelblue", alpha=0.7)
    ax.set_title("Threshold Margin (thr - null_mean)")
    ax.set_xlabel("# files indexed")
    ax.set_ylabel("margin")
    ax.axhline(0, color="r", linestyle="--", alpha=0.5)
    ax.grid(True, axis="y", alpha=0.3)
    ax.set_xticks(ns)

    plt.tight_layout()

    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
        out = save_dir / f"incremental_{domain}.png"
        plt.savefig(out, dpi=150)
        print(f"[plot] 저장: {out}")
    else:
        plt.show()
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="movie",
                        choices=["movie", "music"])
    parser.add_argument("--save", default=None,
                        help="PNG 저장 디렉토리 (없으면 화면 표시)")
    args = parser.parse_args()

    result = run_incremental(args.domain)

    # JSON 저장
    out_dir = Path(args.save) if args.save else Path(_root / "MR_TriCHEF" / "results")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"incremental_{args.domain}.json"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[결과 JSON] {json_path}")

    # 시각화
    save_dir = Path(args.save) if args.save else out_dir
    plot_results(result, save_dir=save_dir)

    # 하드코딩 파라미터 요약
    print("\n[하드코딩 파라미터 현황]")
    for k, v in HARDCODED_PARAMS.items():
        print(f"  {k:<35} = {v}")
    print("\n  → 위 값들이 데이터셋 크기 변화에 따라 얼마나 달라져야 하는지")
    print("    위 4-panel 그래프를 보고 판단하세요.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
