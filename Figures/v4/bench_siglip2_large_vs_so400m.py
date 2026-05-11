"""DI_TriCHEF/scripts/bench_siglip2_large_vs_so400m.py — SigLIP2 모델 비교.

Experiment 2: SO400M (1152d) vs Large (1024d) 임베딩 품질 비교.

방식:
  * Img 도메인에서 100개 이미지 샘플 (캡션 보유 이미지만)
  * 두 모델로 동일 이미지 + L3 캡션을 임베딩
  * 비교 지표:
    1. Cross-modal retrieval: L3 캡션 → 이미지 검색 R@1/R@5 (100-sample)
    2. Image self-retrieval: SO400M 100 query vs 2390 full-corpus cache R@1
    3. Pairwise cosine sim 분포 (image discrimination)
    4. 유효 차원 분석 (PCA explained variance ratio)

결과: DI_TriCHEF/results/{ts}_siglip2_bench.json
"""
from __future__ import annotations

import datetime
import gc
import json
import os
import random
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from config import TRICHEF_CFG  # noqa: E402

# ── 실험 파라미터 ─────────────────────────────────────────────
N_SAMPLES = 100
SEED = 2026
TOPK = 10
BATCH_IMG = 32
BATCH_TXT = 64

MODEL_SO400M = "google/siglip2-so400m-patch16-naflex"
MODEL_LARGE = "google/siglip2-large-patch16-256"

DEVICE = TRICHEF_CFG["DEVICE"]


# ── SigLIP2 임베딩 헬퍼 (모델 파라미터화) ──────────────────────
class SigLIP2Embedder:
    """두 모델을 번갈아 로드하기 위한 파라미터화된 임베더."""

    def __init__(self, model_id: str, device: str = DEVICE):
        self.model_id = model_id
        self.device = device
        self.model = None
        self.proc = None

    def load(self):
        if self.model is not None:
            return
        print(f"[bench] 모델 로드: {self.model_id} ...")
        self.proc = AutoProcessor.from_pretrained(self.model_id)
        self.model = AutoModel.from_pretrained(
            self.model_id,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
        ).to(self.device).eval()
        print(f"[bench] 로드 완료")

    def unload(self):
        if self.model is not None:
            del self.model
            self.model = None
        if self.proc is not None:
            del self.proc
            self.proc = None
        gc.collect()
        if self.device == "cuda":
            torch.cuda.empty_cache()

    @torch.inference_mode()
    def embed_images(self, paths: list[Path]) -> np.ndarray:
        self.load()
        out = []
        for i in range(0, len(paths), BATCH_IMG):
            batch = []
            for p in paths[i:i + BATCH_IMG]:
                with Image.open(p) as img:
                    batch.append(img.convert("RGB"))
            inp = self.proc(images=batch, return_tensors="pt", padding=True).to(self.device)
            mdtype = next(self.model.parameters()).dtype
            inp = {k: v.to(mdtype) if v.is_floating_point() else v
                   for k, v in inp.items()}
            vec = self.model.get_image_features(**inp)
            vec = torch.nn.functional.normalize(vec, dim=-1)
            out.append(vec.cpu().float().numpy())
            if self.device == "cuda":
                torch.cuda.empty_cache()
        return np.vstack(out).astype(np.float32)

    @torch.inference_mode()
    def embed_texts(self, texts: list[str]) -> np.ndarray:
        self.load()
        out = []
        for i in range(0, len(texts), BATCH_TXT):
            inp = self.proc(text=texts[i:i + BATCH_TXT], padding="max_length",
                            truncation=True, return_tensors="pt").to(self.device)
            vec = self.model.get_text_features(**inp)
            vec = torch.nn.functional.normalize(vec, dim=-1)
            out.append(vec.cpu().float().numpy())
        return np.vstack(out).astype(np.float32)


# ── 데이터 로드 ───────────────────────────────────────────────
def _load_samples() -> tuple[list[Path], list[str], list[str]]:
    """이미지 경로 + L3 캡션 샘플링. (paths, captions, ids) 반환."""
    img_dir = ROOT / "Data" / "embedded_DB" / "Img"
    raw_dir = ROOT / "Data" / "raw_DB" / "Img"

    # caption_3stage.json 로드 (L3 캡션 보유 이미지만)
    cap_data = json.loads(
        (img_dir / "caption_3stage.json").read_text(encoding="utf-8")
    )
    cap_ids = cap_data["ids"]
    cap_l3 = cap_data["L3"]
    print(f"[bench] 캡션 보유 이미지: {len(cap_ids)}건")

    # 실제 파일 존재 확인 및 샘플링
    rnd = random.Random(SEED)
    eligible = []
    for i, rid in enumerate(cap_ids):
        p = raw_dir / rid
        if p.exists() and i < len(cap_l3) and cap_l3[i]:
            eligible.append(i)

    picks = rnd.sample(eligible, min(N_SAMPLES, len(eligible)))
    paths = [raw_dir / cap_ids[i] for i in picks]
    captions = [cap_l3[i] for i in picks]
    ids = [cap_ids[i] for i in picks]

    print(f"[bench] 샘플 {len(picks)}건 선정 (존재 확인 완료)")
    return paths, captions, ids


def _load_full_corpus_re() -> tuple[np.ndarray, list[str]]:
    """SO400M Re 전체 코퍼스 캐시 로드."""
    img_dir = ROOT / "Data" / "embedded_DB" / "Img"
    Re = np.load(img_dir / "cache_img_Re_siglip2.npy")
    ids_raw = json.loads(
        (img_dir / "img_ids.json").read_text(encoding="utf-8")
    )
    ids = ids_raw["ids"] if isinstance(ids_raw, dict) else ids_raw
    n = min(Re.shape[0], len(ids))
    return Re[:n], ids[:n]


# ── 평가 함수 ─────────────────────────────────────────────────
def _cross_modal_retrieval(text_vecs: np.ndarray, img_vecs: np.ndarray,
                           ) -> dict:
    """Caption → Image retrieval. text[i] 의 정답은 img[i]."""
    n = text_vecs.shape[0]
    scores = text_vecs @ img_vecs.T  # (N, N) cosine sim
    r1, r5 = 0, 0
    mrr = 0.0
    for i in range(n):
        row = scores[i]
        ranked = np.argsort(-row)
        rank = int(np.where(ranked == i)[0][0]) + 1
        if rank == 1:
            r1 += 1
        if rank <= 5:
            r5 += 1
        mrr += 1.0 / rank
    return {
        "r1": round(r1 / n, 4),
        "r5": round(r5 / n, 4),
        "mrr": round(mrr / n, 4),
    }


def _full_corpus_retrieval(query_vecs: np.ndarray, corpus_vecs: np.ndarray,
                           query_ids: list[str], corpus_ids: list[str],
                           ) -> dict:
    """Full corpus self-retrieval. query[i]의 정답은 query_ids[i]."""
    n = query_vecs.shape[0]
    scores = query_vecs @ corpus_vecs.T  # (N_q, N_corpus)
    r1, r5 = 0, 0
    mrr = 0.0
    missing = 0
    for i in range(n):
        gold = query_ids[i]
        if gold not in corpus_ids:
            missing += 1
            continue
        gold_idx = corpus_ids.index(gold)
        row = scores[i]
        ranked = np.argsort(-row)
        rank = int(np.where(ranked == gold_idx)[0][0]) + 1
        if rank == 1:
            r1 += 1
        if rank <= 5:
            r5 += 1
        mrr += 1.0 / rank
    valid = n - missing
    if valid == 0:
        return {"r1": 0, "r5": 0, "mrr": 0, "missing": missing}
    return {
        "r1": round(r1 / valid, 4),
        "r5": round(r5 / valid, 4),
        "mrr": round(mrr / valid, 4),
        "missing": missing,
    }


def _pairwise_stats(vecs: np.ndarray) -> dict:
    """Pairwise cosine similarity 분포 통계."""
    sim = vecs @ vecs.T  # (N, N)
    n = sim.shape[0]
    # 대각선(자기자신) 제외
    mask = ~np.eye(n, dtype=bool)
    off_diag = sim[mask]
    return {
        "mean": round(float(off_diag.mean()), 6),
        "std": round(float(off_diag.std()), 6),
        "min": round(float(off_diag.min()), 6),
        "max": round(float(off_diag.max()), 6),
        "median": round(float(np.median(off_diag)), 6),
    }


def _effective_dim(vecs: np.ndarray, threshold: float = 0.95) -> dict:
    """PCA explained variance ratio → 유효 차원 수."""
    centered = vecs - vecs.mean(axis=0)
    # SVD (경제적 분해)
    _, s, _ = np.linalg.svd(centered, full_matrices=False)
    var_ratio = (s ** 2) / (s ** 2).sum()
    cumsum = np.cumsum(var_ratio)
    eff_dim_95 = int(np.searchsorted(cumsum, threshold)) + 1
    eff_dim_99 = int(np.searchsorted(cumsum, 0.99)) + 1
    return {
        "total_dim": int(vecs.shape[1]),
        "eff_dim_95": eff_dim_95,
        "eff_dim_99": eff_dim_99,
        "top10_var_pct": round(float(cumsum[9]) * 100, 2) if len(cumsum) >= 10 else None,
        "top50_var_pct": round(float(cumsum[49]) * 100, 2) if len(cumsum) >= 50 else None,
    }


# ── 메인 ──────────────────────────────────────────────────────
def main() -> None:
    paths, captions, sample_ids = _load_samples()
    corpus_Re, corpus_ids = _load_full_corpus_re()
    print(f"[bench] 전체 코퍼스: {corpus_Re.shape[0]} vectors ({corpus_Re.shape[1]}d)")

    results = {}

    # ── SO400M ────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  SO400M ({MODEL_SO400M})")
    print(f"{'='*60}")

    emb_so = SigLIP2Embedder(MODEL_SO400M)

    print("[SO400M] 이미지 임베딩 ...")
    img_so = emb_so.embed_images(paths)
    print(f"  shape: {img_so.shape}")

    print("[SO400M] 텍스트 임베딩 (L3 캡션) ...")
    txt_so = emb_so.embed_texts(captions)
    print(f"  shape: {txt_so.shape}")

    emb_so.unload()

    # Cross-modal
    cm_so = _cross_modal_retrieval(txt_so, img_so)
    print(f"  Cross-modal (caption→image): R@1={cm_so['r1']:.3f}  "
          f"R@5={cm_so['r5']:.3f}  MRR={cm_so['mrr']:.3f}")

    # Full corpus self-retrieval
    fc_so = _full_corpus_retrieval(img_so, corpus_Re, sample_ids, corpus_ids)
    print(f"  Full-corpus self-retrieval:  R@1={fc_so['r1']:.3f}  "
          f"R@5={fc_so['r5']:.3f}  MRR={fc_so['mrr']:.3f}  "
          f"missing={fc_so['missing']}")

    # Pairwise stats
    pw_so = _pairwise_stats(img_so)
    print(f"  Pairwise sim: mean={pw_so['mean']:.4f}  std={pw_so['std']:.4f}")

    # Effective dim
    ed_so = _effective_dim(img_so)
    print(f"  Effective dim: {ed_so['total_dim']}d total, "
          f"95%={ed_so['eff_dim_95']}, 99%={ed_so['eff_dim_99']}")

    results["SO400M"] = {
        "model_id": MODEL_SO400M,
        "dim": int(img_so.shape[1]),
        "cross_modal": cm_so,
        "full_corpus": fc_so,
        "pairwise": pw_so,
        "effective_dim": ed_so,
        "orthogonalizable": False,
    }

    # ── Large ─────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Large ({MODEL_LARGE})")
    print(f"{'='*60}")

    emb_lg = SigLIP2Embedder(MODEL_LARGE)

    print("[Large] 이미지 임베딩 ...")
    img_lg = emb_lg.embed_images(paths)
    print(f"  shape: {img_lg.shape}")

    print("[Large] 텍스트 임베딩 (L3 캡션) ...")
    txt_lg = emb_lg.embed_texts(captions)
    print(f"  shape: {txt_lg.shape}")

    emb_lg.unload()

    # Cross-modal
    cm_lg = _cross_modal_retrieval(txt_lg, img_lg)
    print(f"  Cross-modal (caption→image): R@1={cm_lg['r1']:.3f}  "
          f"R@5={cm_lg['r5']:.3f}  MRR={cm_lg['mrr']:.3f}")

    # Large는 전체 코퍼스 캐시가 없으므로 100-sample 내 self-retrieval
    # (SO400M full-corpus와 직접 비교 불가 — 참고 지표)
    fc_lg_note = "N/A (전체 코퍼스 Large 캐시 없음)"
    print(f"  Full-corpus self-retrieval:  {fc_lg_note}")

    # Pairwise stats
    pw_lg = _pairwise_stats(img_lg)
    print(f"  Pairwise sim: mean={pw_lg['mean']:.4f}  std={pw_lg['std']:.4f}")

    # Effective dim
    ed_lg = _effective_dim(img_lg)
    print(f"  Effective dim: {ed_lg['total_dim']}d total, "
          f"95%={ed_lg['eff_dim_95']}, 99%={ed_lg['eff_dim_99']}")

    results["Large"] = {
        "model_id": MODEL_LARGE,
        "dim": int(img_lg.shape[1]),
        "cross_modal": cm_lg,
        "full_corpus": fc_lg_note,
        "pairwise": pw_lg,
        "effective_dim": ed_lg,
        "orthogonalizable": True,
    }

    # ── 요약 비교 ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Summary Comparison")
    print(f"{'='*60}")
    print(f"{'':>25} {'SO400M':>12} {'Large':>12} {'Delta':>12}")
    print(f"{'-'*60}")
    print(f"{'Dimension':>25} {results['SO400M']['dim']:>12} "
          f"{results['Large']['dim']:>12}")
    print(f"{'Orthogonalizable':>25} {'No':>12} {'Yes':>12}")
    print(f"{'Cross-modal R@1':>25} {cm_so['r1']:>12.3f} "
          f"{cm_lg['r1']:>12.3f} {cm_lg['r1']-cm_so['r1']:>+12.3f}")
    print(f"{'Cross-modal R@5':>25} {cm_so['r5']:>12.3f} "
          f"{cm_lg['r5']:>12.3f} {cm_lg['r5']-cm_so['r5']:>+12.3f}")
    print(f"{'Cross-modal MRR':>25} {cm_so['mrr']:>12.3f} "
          f"{cm_lg['mrr']:>12.3f} {cm_lg['mrr']-cm_so['mrr']:>+12.3f}")
    print(f"{'Pairwise sim (mean)':>25} {pw_so['mean']:>12.4f} "
          f"{pw_lg['mean']:>12.4f} {pw_lg['mean']-pw_so['mean']:>+12.4f}")
    print(f"{'Pairwise sim (std)':>25} {pw_so['std']:>12.4f} "
          f"{pw_lg['std']:>12.4f} {pw_lg['std']-pw_so['std']:>+12.4f}")
    print(f"{'Eff dim (95%)':>25} {ed_so['eff_dim_95']:>12} "
          f"{ed_lg['eff_dim_95']:>12} "
          f"{ed_lg['eff_dim_95']-ed_so['eff_dim_95']:>+12}")
    print(f"{'Eff dim (99%)':>25} {ed_so['eff_dim_99']:>12} "
          f"{ed_lg['eff_dim_99']:>12} "
          f"{ed_lg['eff_dim_99']-ed_so['eff_dim_99']:>+12}")

    # 결과 저장
    report = {
        "experiment": "siglip2_model_comparison",
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "domain": "image",
        "n_samples": len(paths),
        "seed": SEED,
        "models": results,
    }

    out_dir = Path(__file__).resolve().parent  # Figures/v4/
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{ts}_siglip2_bench.json"
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    main()
