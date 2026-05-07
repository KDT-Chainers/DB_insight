"""Doc Im fusion alpha 튜닝 — α·캡션 + (1-α)·본문 가중치 최적화.

unified_engine.py 의 DOC_IM_ALPHA (기본 0.35) 를 다양하게 시도하며 평가.
ground truth: scripts/_ground_truth_doc_body.json (본문 키워드 쿼리)

작업:
  1. cache_doc_page_Im.npy (캡션) + cache_doc_page_Im_body.npy (본문) 로드
  2. α 별로 Im_fused = α·Im_cap + (1-α)·Im_body → renormalize → 평가
  3. 최적 α 보고

사용:
  python scripts/tune_doc_im_alpha.py
  python scripts/tune_doc_im_alpha.py --alphas 0.20,0.35,0.50,0.65,0.80
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("[tune_doc_im_alpha] 시작", flush=True)

ROOT = Path(__file__).resolve().parents[1]
DOC_CACHE = ROOT / "Data" / "embedded_DB" / "Doc"
GT_PATH   = ROOT / "scripts" / "_ground_truth_doc_body.json"


def evaluate_with_alpha(alpha: float, eng, query_obj_list: list[dict],
                        Im_cap, Im_body, top_k: int = 10) -> dict:
    """α·Im_cap + (1-α)·Im_body 로 Im 채널 교체 후 평가."""
    import numpy as np

    # 새 Im 채널 계산
    Im_fused = alpha * Im_cap + (1 - alpha) * Im_body
    norms = np.linalg.norm(Im_fused, axis=1, keepdims=True)
    Im_new = Im_fused / np.maximum(norms, 1e-9)

    # engine cache 의 Im 임시 교체
    d = eng._cache["doc_page"]
    Im_orig = d["Im"]
    d["Im"] = Im_new
    try:
        n_hit = 0
        n_total = 0
        mrr_sum = 0.0
        for qo in query_obj_list:
            q = qo["query"]
            expected = set(b.lower() for b in qo.get("expected_basenames", []))
            if not expected:
                continue
            n_total += 1
            try:
                results = eng.search(q, "doc_page", topk=top_k,
                                     use_lexical=True, use_asf=True, pool=200)
            except Exception:
                continue
            positions = []
            for i, r in enumerate(results, 1):
                if r.id.startswith("page_images/"):
                    fname = r.id.split("/", 2)[1] + ".pdf"
                else:
                    fname = r.id.replace("\\", "/").rsplit("/", 1)[-1]
                if fname.lower() in expected:
                    positions.append(i)
            if positions:
                n_hit += 1
                mrr_sum += 1.0 / positions[0]
    finally:
        # Im 원복
        d["Im"] = Im_orig

    return {
        "alpha": alpha,
        "n_total": n_total,
        "n_hit": n_hit,
        "recall": n_hit / max(n_total, 1),
        "mrr": mrr_sum / max(n_total, 1),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--alphas", default="0.20,0.35,0.50,0.65,0.80",
                        help="콤마 구분 α 값들")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--ground-truth", default=str(GT_PATH))
    args = parser.parse_args()

    gt_path = Path(args.ground_truth)
    if not gt_path.exists():
        print(f"[ERROR] ground truth 없음: {gt_path}", flush=True)
        return 2
    queries = json.loads(gt_path.read_text(encoding="utf-8"))
    print(f"ground truth 쿼리: {len(queries)}", flush=True)

    alphas = [float(a) for a in args.alphas.split(",")]
    print(f"테스트 α: {alphas}", flush=True)

    # 엔진 + 캐시 로드
    sys.path.insert(0, str(ROOT / "App" / "backend"))
    import os
    os.environ.setdefault("TRICHEF_USE_RERANKER", "0")
    from services.trichef.unified_engine import TriChefEngine
    import numpy as np
    print("\n엔진 로드 중...", flush=True)
    eng = TriChefEngine()

    # 원본 Im_caption (이미 fusion 된 상태일 가능성) → caption 만 분리 어려움
    # 따라서 Im_caption.npy 와 Im_body.npy 직접 로드
    Im_cap_path = DOC_CACHE / "cache_doc_page_Im.npy"
    Im_body_path = DOC_CACHE / "cache_doc_page_Im_body.npy"
    if not Im_body_path.exists():
        print(f"[ERROR] {Im_body_path} 없음 — Doc Im_body 재구축 필요", flush=True)
        return 2
    Im_cap = np.load(Im_cap_path)
    Im_body = np.load(Im_body_path)
    if Im_cap.shape != Im_body.shape:
        print(f"[ERROR] shape mismatch: cap {Im_cap.shape} != body {Im_body.shape}", flush=True)
        return 2
    print(f"  Im_cap:  {Im_cap.shape}", flush=True)
    print(f"  Im_body: {Im_body.shape}", flush=True)

    # α 별 평가
    print(f"\n{'α':<6} {'쿼리':<8} {'Recall':<10} {'MRR':<8}")
    print("-" * 40)
    results = []
    for alpha in alphas:
        t0 = time.time()
        r = evaluate_with_alpha(alpha, eng, queries, Im_cap, Im_body, args.top_k)
        elapsed = time.time() - t0
        results.append(r)
        print(f"{alpha:<6.2f} {r['n_total']:<8} "
              f"{r['recall']*100:>5.1f}%    {r['mrr']:<8.3f} "
              f"({elapsed:.1f}s)", flush=True)

    # 최적 α
    best = max(results, key=lambda r: (r["recall"], r["mrr"]))
    print(f"\n최적 α: {best['alpha']} (Recall {best['recall']*100:.1f}%, MRR {best['mrr']:.3f})",
          flush=True)
    print(f"\n적용 방법: App/backend/config.py 의 TRICHEF_CFG['DOC_IM_ALPHA'] = {best['alpha']}",
          flush=True)


if __name__ == "__main__":
    sys.exit(main())
