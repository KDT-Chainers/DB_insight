"""DI_TriCHEF/scripts/hermitian_ab_sweep.py — Hermitian alpha/beta grid search.

Experiment 1: LOO Self-Retrieval 기반 alpha/beta 최적 조합 탐색.

방식:
  * Doc 도메인 캐시(.npy)를 직접 로드 (TriChefEngine 우회)
  * body_texts 앞 100자를 쿼리로 사용 (loo_eval_doc.py 동일 프로토콜)
  * 쿼리 임베딩 1회 생성 후 15개 (alpha, beta) 조합에 재사용
  * q_Z = zeros (unified_engine.py:322 동일 — 텍스트 쿼리 시 Z 채널 무효화)
  * Doc Im_body fusion (DOC_IM_ALPHA=0.20) 재현

Grid: alpha in {0.2, 0.4, 0.6, 0.8, 1.0} x beta in {0.0, 0.2, 0.4}

결과: DI_TriCHEF/results/{ts}_hermitian_ab_sweep.json
"""
from __future__ import annotations

import datetime
import json
import os
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from config import TRICHEF_CFG  # noqa: E402
from services.trichef import tri_gs  # noqa: E402

# ── 실험 파라미터 ─────────────────────────────────────────────
N_SAMPLES = 150
SEED = 2026
QUERY_CHARS = 100
TOPK = 10

ALPHAS = [0.2, 0.4, 0.6, 0.8, 1.0]
BETAS = [0.0, 0.2, 0.4]

DOC_IM_ALPHA = float(TRICHEF_CFG.get("DOC_IM_ALPHA", 0.20))


# ── 데이터 로드 ───────────────────────────────────────────────
def _load_corpus() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str], list[str]]:
    """Doc 도메인 캐시 + body_texts 로드. unified_engine.py 와 동일한 Im fusion 적용."""
    doc_dir = ROOT / "Data" / "embedded_DB" / "Doc"

    print(f"[sweep] 캐시 로드: {doc_dir}")
    d_Re = np.load(doc_dir / "cache_doc_page_Re.npy")       # (N, 1152)
    d_Im_cap = np.load(doc_dir / "cache_doc_page_Im.npy")   # (N, 1024)
    d_Z = np.load(doc_dir / "cache_doc_page_Z.npy")         # (N, 1024)

    # Im_body fusion (unified_engine.py:170-178 재현)
    body_path = doc_dir / "cache_doc_page_Im_body.npy"
    if body_path.exists():
        d_Im_body = np.load(body_path)
        if d_Im_body.shape == d_Im_cap.shape:
            d_Im = DOC_IM_ALPHA * d_Im_cap + (1.0 - DOC_IM_ALPHA) * d_Im_body
            norms = np.linalg.norm(d_Im, axis=1, keepdims=True)
            d_Im = d_Im / np.maximum(norms, 1e-9)
            print(f"[sweep] Im_body fusion 적용 (DOC_IM_ALPHA={DOC_IM_ALPHA:.2f})")
        else:
            print(f"[sweep] Im_body shape 불일치 ({d_Im_body.shape} vs {d_Im_cap.shape}) — fusion 스킵")
            d_Im = d_Im_cap
    else:
        print("[sweep] Im_body 없음 — caption Im 단독 사용")
        d_Im = d_Im_cap

    # ids
    ids_path = doc_dir / "doc_page_ids.json"
    ids_raw = json.loads(ids_path.read_text(encoding="utf-8"))
    ids = ids_raw["ids"] if isinstance(ids_raw, dict) else ids_raw

    # body_texts
    bodies_path = doc_dir / "_body_texts.json"
    bodies = json.loads(bodies_path.read_text(encoding="utf-8"))

    # 길이 정합
    n = min(d_Re.shape[0], len(ids), len(bodies))
    if d_Re.shape[0] != len(ids) or len(ids) != len(bodies):
        print(f"[sweep] 길이 불일치: Re={d_Re.shape[0]}, ids={len(ids)}, "
              f"bodies={len(bodies)} -> 절단 {n}")
    d_Re = d_Re[:n]
    d_Im = d_Im[:n]
    d_Z = d_Z[:n]
    ids = ids[:n]
    bodies = bodies[:n]

    print(f"[sweep] 코퍼스: {n} pages, Re={d_Re.shape}, Im={d_Im.shape}, Z={d_Z.shape}")
    return d_Re, d_Im, d_Z, ids, bodies


def _sample_queries(bodies: list[str], ids: list[str],
                    n: int) -> list[tuple[str, str, int]]:
    """body 텍스트에서 쿼리 샘플링. (query_text, gold_id, corpus_idx) 반환."""
    rnd = random.Random(SEED)
    eligible = [i for i, b in enumerate(bodies)
                if isinstance(b, str) and len(b.strip()) >= 40]
    picks = rnd.sample(eligible, min(n, len(eligible)))
    return [(bodies[i].strip()[:QUERY_CHARS], ids[i], i) for i in picks]


def _embed_queries(queries: list[tuple[str, str, int]],
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """150개 쿼리를 일괄 임베딩. (q_Re, q_Im, q_Z) 반환."""
    from embedders.trichef import siglip2_re  # noqa: E402
    from embedders.trichef import bgem3_caption_im as bge_im  # noqa: E402

    texts = [q for q, _, _ in queries]

    print(f"[sweep] SigLIP2 Re 임베딩 ({len(texts)}건) ...")
    q_Re = siglip2_re.embed_texts(texts)  # (N, 1152)

    print(f"[sweep] BGE-M3 Im 임베딩 ({len(texts)}건) ...")
    q_Im = bge_im.embed_query(texts)  # (N, 1024)

    q_Z = np.zeros_like(q_Im)  # (N, 1024) — unified_engine.py:322 동일

    print(f"[sweep] 쿼리 임베딩 완료: Re={q_Re.shape}, Im={q_Im.shape}, Z={q_Z.shape}")
    return q_Re, q_Im, q_Z


# ── 평가 ──────────────────────────────────────────────────────
def _eval_grid(q_Re: np.ndarray, q_Im: np.ndarray, q_Z: np.ndarray,
               d_Re: np.ndarray, d_Im: np.ndarray, d_Z: np.ndarray,
               gold_indices: list[int],
               ) -> list[dict]:
    """15개 (alpha, beta) 조합에 대해 R@1/R@5/MRR@10 측정."""
    results = []
    n_q = q_Re.shape[0]

    for alpha in ALPHAS:
        for beta in BETAS:
            # (N_query, N_corpus) 점수 행렬 — 단일 행렬곱
            scores = tri_gs.hermitian_score(
                q_Re, q_Im, q_Z,
                d_Re, d_Im, d_Z,
                alpha=alpha, beta=beta,
            )

            r1 = 0
            r5 = 0
            mrr = 0.0

            for qi in range(n_q):
                row = scores[qi]
                # top-K 인덱스 (내림차순)
                topk_idx = np.argpartition(-row, TOPK)[:TOPK]
                topk_idx = topk_idx[np.argsort(-row[topk_idx])]

                gold = gold_indices[qi]
                rank = 0
                for r, idx in enumerate(topk_idx, 1):
                    if idx == gold:
                        rank = r
                        break

                if rank >= 1:
                    if rank == 1:
                        r1 += 1
                    if rank <= 5:
                        r5 += 1
                    mrr += 1.0 / rank

            entry = {
                "alpha": alpha,
                "beta": beta,
                "r1": round(r1 / n_q, 4),
                "r5": round(r5 / n_q, 4),
                "mrr10": round(mrr / n_q, 4),
                "n": n_q,
            }
            results.append(entry)
            print(f"  alpha={alpha:.1f}  beta={beta:.1f}  "
                  f"R@1={entry['r1']:.3f}  R@5={entry['r5']:.3f}  "
                  f"MRR@10={entry['mrr10']:.3f}")

    return results


# ── 메인 ──────────────────────────────────────────────────────
def main() -> None:
    d_Re, d_Im, d_Z, ids, bodies = _load_corpus()
    queries = _sample_queries(bodies, ids, N_SAMPLES)
    print(f"[sweep] 샘플 {len(queries)}건 추출 (앞 {QUERY_CHARS}자)")

    q_Re, q_Im, q_Z = _embed_queries(queries)
    gold_indices = [idx for _, _, idx in queries]

    print(f"\n{'='*65}")
    print(f"  Hermitian alpha/beta Grid Search  ({len(ALPHAS)}x{len(BETAS)}={len(ALPHAS)*len(BETAS)} 조합)")
    print(f"{'='*65}")

    results = _eval_grid(q_Re, q_Im, q_Z, d_Re, d_Im, d_Z, gold_indices)

    # 최적 조합 찾기
    best = max(results, key=lambda r: (r["r5"], r["mrr10"]))
    print(f"\n{'='*65}")
    print(f"  BEST (R@5 기준): alpha={best['alpha']}, beta={best['beta']}")
    print(f"  R@1={best['r1']:.3f}  R@5={best['r5']:.3f}  MRR@10={best['mrr10']:.3f}")

    # 현재 기본값과 비교
    default = next((r for r in results
                    if r["alpha"] == 0.4 and r["beta"] == 0.2), None)
    if default:
        print(f"\n  DEFAULT (alpha=0.4, beta=0.2):")
        print(f"  R@1={default['r1']:.3f}  R@5={default['r5']:.3f}  "
              f"MRR@10={default['mrr10']:.3f}")
        if best != default:
            d_r5 = best["r5"] - default["r5"]
            print(f"  -> 최적 vs 기본값: R@5 차이 = {d_r5:+.4f}")
        else:
            print(f"  -> 현재 기본값이 최적!")

    # beta 무관 검증 (q_Z=zeros -> beta 변화에 점수 불변 예상)
    print(f"\n  [검증] beta 변동 시 R@5 변화:")
    for alpha in ALPHAS:
        vals = [r["r5"] for r in results if r["alpha"] == alpha]
        spread = max(vals) - min(vals)
        print(f"    alpha={alpha:.1f}: beta별 R@5 = {vals}  spread={spread:.4f}")

    # 요약 테이블
    print(f"\n{'='*65}")
    print(f"  R@5 Heatmap (alpha x beta)")
    print(f"{'='*65}")
    header = f"{'alpha':>8}" + "".join(f"  beta={b:.1f}" for b in BETAS)
    print(header)
    print("-" * len(header))
    for alpha in ALPHAS:
        row = f"{alpha:>8.1f}"
        for beta in BETAS:
            r = next(r for r in results
                     if r["alpha"] == alpha and r["beta"] == beta)
            marker = " *" if r == best else "  "
            row += f"  {r['r5']:.3f}{marker}"
        print(row)

    # 결과 저장
    report = {
        "experiment": "hermitian_ab_sweep",
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "domain": "doc_page",
        "n_samples": len(queries),
        "query_chars": QUERY_CHARS,
        "topk": TOPK,
        "seed": SEED,
        "doc_im_alpha": DOC_IM_ALPHA,
        "grid": {"alphas": ALPHAS, "betas": BETAS},
        "best": best,
        "results": results,
    }

    out_dir = Path(__file__).resolve().parent  # Figures/v4/
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{ts}_hermitian_ab_sweep.json"
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    main()
