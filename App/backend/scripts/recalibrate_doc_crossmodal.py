"""scripts/recalibrate_doc_crossmodal.py — doc_page crossmodal 재캘리브레이션

Im_body fusion + 다양한 alpha 값에서 실제 query-doc null 분포를 측정하여
trichef_calibration.json 의 doc_page threshold를 갱신한다.

실행: python scripts/recalibrate_doc_crossmodal.py
"""
from __future__ import annotations
import json, random, sys, time
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PATHS, TRICHEF_CFG

CALIB_PATH = Path(PATHS["EMBEDDED_DB"]) / "trichef_calibration.json"
CACHE      = Path(PATHS["TRICHEF_DOC_CACHE"])
EXTRACT    = Path(PATHS["TRICHEF_DOC_EXTRACT"])
CAP_BASE   = EXTRACT / "captions"

SAMPLE_Q   = 300   # pseudo-query 캡션 샘플 수
PAIRS_PER_Q = 10   # 쿼리당 random non-self pair 수
FAR        = 0.05  # 목표 False Alarm Rate


def _inv_phi(p: float) -> float:
    """표준정규 분위수 근사 (Acklam)."""
    import math
    a = [-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
          4.374664141464968e+00,  2.938163982698783e+00]
    d = [ 7.784695709041462e-03,  3.224671290700398e-01,
          2.445134137142996e+00,  3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) \
               / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= ph:
        q = p - 0.5; r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q \
               / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) \
             / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def load_doc_cache():
    """Im_body fusion 적용된 doc_page 캐시 로드."""
    Re     = np.load(CACHE / "cache_doc_page_Re.npy").astype(np.float32)
    Im_raw = np.load(CACHE / "cache_doc_page_Im.npy").astype(np.float32)
    Z      = np.load(CACHE / "cache_doc_page_Z.npy").astype(np.float32)
    ids    = json.loads((CACHE / "doc_page_ids.json").read_text(encoding="utf-8"))["ids"]

    body_path = CACHE / "cache_doc_page_Im_body.npy"
    if body_path.exists():
        Im_body = np.load(body_path).astype(np.float32)
        if Im_body.shape == Im_raw.shape:
            a = float(TRICHEF_CFG.get("DOC_IM_ALPHA", 0.20))
            Im_fused = a * Im_raw + (1.0 - a) * Im_body
            norms = np.linalg.norm(Im_fused, axis=1, keepdims=True)
            Im = Im_fused / np.maximum(norms, 1e-9)
            print(f"  Im_body fusion: alpha={a}, shape={Im.shape}")
        else:
            Im = Im_raw
            print(f"  Im_body shape mismatch — Im_raw 사용")
    else:
        Im = Im_raw
        print("  Im_body 없음 — Im_raw 사용")

    # L2 정규화
    Im = Im / np.maximum(np.linalg.norm(Im, axis=1, keepdims=True), 1e-9)
    return Re, Im, Z, ids


def collect_captions(ids: list[str], n: int = SAMPLE_Q) -> list[tuple[int, str]]:
    """캡션 파일에서 pseudo-query 샘플 수집."""
    rng = random.Random(42)
    indices = list(range(len(ids)))
    rng.shuffle(indices)

    samples: list[tuple[int, str]] = []
    for i in indices:
        if len(samples) >= n:
            break
        parts = ids[i].split("/")
        if len(parts) < 3:
            continue
        folder, page_file = parts[1], parts[2]
        stem = Path(page_file).stem
        cap_path = CAP_BASE / folder / f"{stem}.txt"
        if cap_path.exists():
            try:
                text = cap_path.read_text(encoding="utf-8", errors="replace").strip()
                if len(text) > 30:
                    samples.append((i, text[:500]))
            except Exception:
                pass
    print(f"  캡션 샘플: {len(samples)}개")
    return samples


def measure_null(Re, Im, Z, samples, alpha: float, n_pairs: int = PAIRS_PER_Q) -> dict:
    """crossmodal null 분포 측정 (쿼리→random non-self 문서)."""
    from embedders.trichef import siglip2_re, bgem3_caption_im as bgem3
    from services.trichef import tri_gs

    N = Re.shape[0]
    nprng = np.random.default_rng(42)

    src_indices = [i for i, _ in samples]
    texts = [t for _, t in samples]

    print(f"  쿼리 임베딩 중 ({len(texts)}개)...")
    q_Re = siglip2_re.embed_texts(texts)
    q_Re = q_Re / np.maximum(np.linalg.norm(q_Re, axis=1, keepdims=True), 1e-9)
    q_Im = bgem3.embed_query(texts)
    q_Im = q_Im / np.maximum(np.linalg.norm(q_Im, axis=1, keepdims=True), 1e-9)
    q_Z  = np.zeros_like(q_Im)

    scores: list[float] = []
    for k, i_src in enumerate(src_indices):
        j_idx = nprng.integers(0, N, n_pairs * 3)
        j_idx = j_idx[j_idx != i_src][:n_pairs]
        if len(j_idx) == 0:
            continue
        s = tri_gs.hermitian_score(
            q_Re[k:k+1], q_Im[k:k+1], q_Z[k:k+1],
            Re[j_idx], Im[j_idx], Z[j_idx],
            alpha=alpha,
        )[0]
        scores.extend(float(x) for x in s)

    arr = np.array(scores, dtype=np.float32)
    mu  = float(arr.mean())
    sig = float(arr.std())
    thr = mu + _inv_phi(1 - FAR) * sig
    p90 = float(np.percentile(arr, 90))
    p95 = float(np.percentile(arr, 95))
    p99 = float(np.percentile(arr, 99))
    return {
        "mu": mu, "sigma": sig, "threshold": thr,
        "p90": p90, "p95": p95, "p99": p99,
        "n_scores": len(arr),
    }


def main():
    print("=== doc_page crossmodal 재캘리브레이션 ===")
    t0 = time.time()

    print("\n[1] 캐시 로드...")
    Re, Im, Z, ids = load_doc_cache()
    print(f"  N={len(ids):,}")

    print("\n[2] 캡션 샘플 수집...")
    samples = collect_captions(ids, SAMPLE_Q)
    if len(samples) < 50:
        print("  캡션 샘플 부족 — 중단")
        return

    results: dict[float, dict] = {}
    for alpha in [0.4, 0.8]:
        print(f"\n[3] alpha={alpha} null 분포 측정...")
        r = measure_null(Re, Im, Z, samples, alpha)
        results[alpha] = r
        print(f"  mu={r['mu']:.4f}  sigma={r['sigma']:.4f}  threshold={r['threshold']:.4f}")
        print(f"  p90={r['p90']:.4f}  p95={r['p95']:.4f}  p99={r['p99']:.4f}")
        print(f"  n_scores={r['n_scores']:,}")

    # 결과 비교
    print("\n=== 결과 비교 ===")
    for alpha, r in results.items():
        print(f"  alpha={alpha}: threshold={r['threshold']:.4f} "
              f"(mu={r['mu']:.4f} + {_inv_phi(1-FAR):.2f}σ × {r['sigma']:.4f})")

    # 선택: alpha=0.8 사용
    chosen_alpha = 0.8
    chosen = results[chosen_alpha]

    print(f"\n✅ 선택: alpha={chosen_alpha}, threshold={chosen['threshold']:.4f}")

    # trichef_calibration.json 업데이트
    calib_path = CALIB_PATH
    if calib_path.exists():
        data = json.loads(calib_path.read_text(encoding="utf-8"))
    else:
        data = {}

    data["doc_page"] = {
        "mu_null": chosen["mu"],
        "sigma_null": chosen["sigma"],
        "abs_threshold": round(chosen["threshold"], 4),
        "far": FAR,
        "N": len(ids),
        "method": "crossmodal_v2_alpha08",
        "alpha": chosen_alpha,
        "n_queries": len(samples),
        "n_scores": chosen["n_scores"],
        "also_alpha04": {
            "mu_null": results[0.4]["mu"],
            "sigma_null": results[0.4]["sigma"],
            "threshold": round(results[0.4]["threshold"], 4),
        },
    }
    calib_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  캘리브레이션 저장: {calib_path}")
    print(f"\n=== 완료 ({time.time()-t0:.1f}s) ===")
    print(f"  다음 단계: unified_engine.py alpha=0.4→0.8 변경 후 백엔드 재시작")


if __name__ == "__main__":
    main()
