"""scripts/eval_miracl_ko.py — MIRACL-ko 공통 평가 코어.

MIRACL-ko corpus(1.5 M passages) + queries(213 dev) 를 다운로드/로드하고,
Retriever Protocol 을 구현한 baseline 을 받아 nDCG@10 / R@100 / MRR 을 계산한다.
결과는 bench_results/miracl_ko_{system}_{YYYYMMDD_HHMMSS}.json 에 저장.

CLI usage:
    python scripts/eval_miracl_ko.py --system bgem3 --top-k 100
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import math
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

# ── 결정론적 재현성 (논문 §V-E, Table VII, Fig. 7) ─────────────────────────────
# 논문 보고 값(MIRACL-ko nDCG@10=77.82, R@100=95.46, MRR=76.56)과의 재현성을 위해
# 평가 시점에 RNG 시드를 42로 고정한다. FAISS IndexFlatIP 자체는 결정론적이지만
# 모델 로드/임베딩 경로의 어떤 우발적 비결정성도 차단하기 위해 통일.
GLOBAL_SEED: int = 2026


def set_global_seed(seed: int = GLOBAL_SEED) -> None:
    """Python·NumPy·PyTorch RNG 시드 일괄 설정. PyTorch 미설치 환경에서도 안전."""
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import torch  # type: ignore

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


# 모듈 임포트 시점에 즉시 시드 고정 — baseline 모듈이 로드되기 전에 효과 발휘.
set_global_seed(GLOBAL_SEED)

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
BENCH_RESULTS_DIR = ROOT / "bench_results"
CACHE_DIR = ROOT / "Data" / "cache" / "miracl_ko"

BENCH_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("eval_miracl_ko")

# ── Retriever Protocol ────────────────────────────────────────────────────────


@runtime_checkable
class Retriever(Protocol):
    """통일 인터페이스 — 각 baseline script 가 구현해야 할 Protocol."""

    def encode_passages(self, passages: list[str]) -> np.ndarray:
        """패시지 배치 인코딩. (N, d) float32 반환."""
        ...

    def encode_query(self, query: str) -> np.ndarray:
        """쿼리 1건 인코딩. (d,) float32 반환."""
        ...

    def search(
        self,
        query_vec: np.ndarray,
        passage_mat: np.ndarray,
        top_k: int = 100,
    ) -> list[tuple[int, float]]:
        """(idx, score) 리스트 — top_k 개, 내림차순."""
        ...


# ── 데이터 로드 ───────────────────────────────────────────────────────────────


def _hf_cache_env() -> dict[str, str]:
    """HuggingFace datasets 캐시 디렉토리를 CACHE_DIR 로 지정."""
    env = os.environ.copy()
    env["HF_DATASETS_CACHE"] = str(CACHE_DIR)
    return env


def load_miracl_ko(split: str = "dev") -> tuple[list[dict], list[dict]]:
    """MIRACL-ko corpus 와 queries 를 HuggingFace datasets 에서 로드.

    Returns:
        corpus  : list of {"docid": str, "title": str, "text": str}
        queries : list of {"query_id": str, "query": str,
                           "positive_passages": [...], "negative_passages": [...]}
    """
    try:
        from datasets import load_dataset
    except ImportError:
        logger.error(
            "datasets 패키지가 없습니다. pip install datasets>=2.14 를 실행하세요."
        )
        sys.exit(1)

    os.environ["HF_DATASETS_CACHE"] = str(CACHE_DIR)

    logger.info("MIRACL-ko corpus 로드 중 (miracl/miracl-corpus, language=ko) …")
    try:
        corpus_ds = load_dataset(
            "miracl/miracl-corpus",
            "ko",
            split="train",
            trust_remote_code=True,
        )
    except Exception as exc:
        logger.error(f"corpus 로드 실패: {exc}")
        raise

    corpus: list[dict] = [
        {
            "docid": row["docid"],
            "title": row.get("title", ""),
            "text": row["text"],
        }
        for row in corpus_ds
    ]
    logger.info(f"corpus 로드 완료 — {len(corpus):,} passages")

    logger.info(f"MIRACL-ko queries 로드 중 (split={split}) …")
    try:
        query_ds = load_dataset(
            "miracl/miracl",
            "ko",
            split=split,
            trust_remote_code=True,
        )
    except Exception as exc:
        logger.error(f"queries 로드 실패: {exc}")
        raise

    queries: list[dict] = list(query_ds)
    logger.info(f"queries 로드 완료 — {len(queries):,} queries")
    return corpus, queries


# ── passage 행렬 구축 (메모리 효율적 배치) ───────────────────────────────────


def build_passage_matrix(
    retriever: Retriever,
    corpus: list[dict],
    batch_size: int = 32,
) -> tuple[np.ndarray, list[str]]:
    """corpus 전체를 배치 인코딩하여 (N, d) float32 행렬과 docid 리스트 반환.

    1.5 M × 1024d × 4 byte ≈ 6 GB. GPU 환경에서 float16 으로 절반 절약 가능.
    numpy 행렬은 CPU RAM 에 유지.
    """
    docids: list[str] = [doc["docid"] for doc in corpus]
    texts: list[str] = [
        (doc["title"] + " " + doc["text"]).strip() if doc.get("title") else doc["text"]
        for doc in corpus
    ]
    n = len(texts)
    logger.info(f"passage 인코딩 시작 — {n:,} passages, batch_size={batch_size}")

    # 첫 배치로 차원 확인
    first_batch = texts[:batch_size]
    first_vecs = retriever.encode_passages(first_batch)
    dim = first_vecs.shape[1]
    logger.info(f"embedding dim={dim}")

    # 전체 행렬 pre-allocate (float32)
    mat = np.empty((n, dim), dtype=np.float32)
    mat[: len(first_batch)] = first_vecs

    t0 = time.time()
    for start in range(batch_size, n, batch_size):
        end = min(start + batch_size, n)
        batch = texts[start:end]
        try:
            vecs = retriever.encode_passages(batch)
        except MemoryError:
            logger.warning(
                f"OOM at batch {start}–{end}. batch_size 를 줄이거나 "
                "FAISS 를 사용하세요."
            )
            raise
        mat[start:end] = vecs

        if (start // batch_size) % 200 == 0:
            elapsed = time.time() - t0
            pct = end / n * 100
            logger.info(
                f"  인코딩 진행: {end:,}/{n:,} ({pct:.1f}%) — {elapsed:.0f}s"
            )

    logger.info(
        f"passage 인코딩 완료 — shape={mat.shape}, "
        f"elapsed={time.time() - t0:.0f}s"
    )
    return mat, docids


# ── 메트릭 계산 ───────────────────────────────────────────────────────────────


def _dcg(rel_scores: list[float]) -> float:
    """Discounted Cumulative Gain."""
    return sum(
        r / math.log2(i + 2) for i, r in enumerate(rel_scores)
    )


def compute_ndcg_at_k(
    ranked_docids: list[str],
    positive_docids: set[str],
    k: int = 10,
) -> float:
    """nDCG@k (binary relevance)."""
    rels = [1.0 if d in positive_docids else 0.0 for d in ranked_docids[:k]]
    dcg = _dcg(rels)
    ideal = _dcg(sorted(rels, reverse=True))
    return dcg / ideal if ideal > 0 else 0.0


def compute_recall_at_k(
    ranked_docids: list[str],
    positive_docids: set[str],
    k: int = 100,
) -> float:
    """Recall@k."""
    if not positive_docids:
        return 0.0
    top_k = set(ranked_docids[:k])
    return len(top_k & positive_docids) / len(positive_docids)


def compute_mrr(
    ranked_docids: list[str],
    positive_docids: set[str],
    k: int = 100,
) -> float:
    """Mean Reciprocal Rank (MRR@k)."""
    for rank, docid in enumerate(ranked_docids[:k], start=1):
        if docid in positive_docids:
            return 1.0 / rank
    return 0.0


# ── FAISS 검색 (optional) ─────────────────────────────────────────────────────


def faiss_search(
    query_vec: np.ndarray,
    passage_mat: np.ndarray,
    top_k: int = 100,
) -> list[tuple[int, float]]:
    """FAISS IndexFlatIP 로 최근접 top_k 검색. faiss 없으면 numpy matmul fallback."""
    try:
        import faiss  # type: ignore

        index = faiss.IndexFlatIP(passage_mat.shape[1])
        # float32 보장
        mat_f32 = np.ascontiguousarray(passage_mat, dtype=np.float32)
        index.add(mat_f32)
        q = np.ascontiguousarray(query_vec.reshape(1, -1), dtype=np.float32)
        scores, indices = index.search(q, top_k)
        return [(int(idx), float(sc)) for idx, sc in zip(indices[0], scores[0]) if idx >= 0]
    except ImportError:
        logger.warning("faiss 없음 → numpy matmul fallback (느림)")
        sims = passage_mat @ query_vec.astype(np.float32)
        top_idx = np.argpartition(-sims, min(top_k, len(sims) - 1))[:top_k]
        top_idx = top_idx[np.argsort(-sims[top_idx])]
        return [(int(i), float(sims[i])) for i in top_idx]


# ── 평가 루프 ─────────────────────────────────────────────────────────────────


def evaluate(
    retriever: Retriever,
    corpus: list[dict],
    queries: list[dict],
    top_k: int = 100,
    batch_size: int = 32,
    system_name: str = "unknown",
) -> dict:
    """전체 평가 실행. query-level 결과 + aggregated 집계 반환."""
    passage_mat, docids = build_passage_matrix(retriever, corpus, batch_size=batch_size)
    docid_to_idx: dict[str, int] = {d: i for i, d in enumerate(docids)}

    query_results: list[dict] = []
    t0 = time.time()

    for qi, q_item in enumerate(queries):
        qid: str = str(q_item.get("query_id", qi))
        query_text: str = q_item["query"]

        # positive passage ids
        positive_docids: set[str] = {
            p["docid"]
            for p in q_item.get("positive_passages", [])
        }

        # 쿼리 인코딩
        try:
            q_vec = retriever.encode_query(query_text)
        except Exception as exc:
            logger.warning(f"쿼리 {qid} 인코딩 실패: {exc} — 스킵")
            continue

        # 검색
        try:
            hits = retriever.search(q_vec, passage_mat, top_k=top_k)
        except Exception as exc:
            logger.warning(f"쿼리 {qid} 검색 실패: {exc} — 스킵")
            continue

        ranked_docids: list[str] = [docids[idx] for idx, _ in hits]

        ndcg10 = compute_ndcg_at_k(ranked_docids, positive_docids, k=10)
        r100 = compute_recall_at_k(ranked_docids, positive_docids, k=top_k)
        mrr = compute_mrr(ranked_docids, positive_docids, k=top_k)

        query_results.append(
            {
                "query_id": qid,
                "query": query_text,
                "ndcg@10": round(ndcg10, 6),
                f"r@{top_k}": round(r100, 6),
                "mrr": round(mrr, 6),
                "n_positive": len(positive_docids),
                "ranked_top10": ranked_docids[:10],
            }
        )

        if (qi + 1) % 50 == 0:
            logger.info(
                f"  평가 진행: {qi + 1}/{len(queries)} queries — "
                f"{time.time() - t0:.0f}s"
            )

    # 집계
    n = len(query_results)
    if n == 0:
        logger.error("평가된 query 가 0 건입니다.")
        aggregated = {"ndcg@10": 0.0, f"r@{top_k}": 0.0, "mrr": 0.0, "n_queries": 0}
    else:
        aggregated = {
            "ndcg@10": round(sum(r["ndcg@10"] for r in query_results) / n, 6),
            f"r@{top_k}": round(sum(r[f"r@{top_k}"] for r in query_results) / n, 6),
            "mrr": round(sum(r["mrr"] for r in query_results) / n, 6),
            "n_queries": n,
        }
    logger.info(
        f"평가 완료 — nDCG@10={aggregated['ndcg@10']:.4f}, "
        f"R@{top_k}={aggregated[f'r@{top_k}']:.4f}, "
        f"MRR={aggregated['mrr']:.4f}"
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    result = {
        "system": system_name,
        "timestamp": ts,
        "top_k": top_k,
        "n_corpus": len(corpus),
        "aggregated": aggregated,
        "query_results": query_results,
    }
    return result


# ── 결과 저장 ─────────────────────────────────────────────────────────────────


def save_result(result: dict, system_name: str) -> Path:
    """결과를 bench_results/miracl_ko_{system}_{ts}.json 에 저장."""
    ts = result.get("timestamp", datetime.now().strftime("%Y%m%d_%H%M%S"))
    fname = f"miracl_ko_{system_name}_{ts}.json"
    out_path = BENCH_RESULTS_DIR / fname
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info(f"결과 저장: {out_path}")
    return out_path


# ── CLI ───────────────────────────────────────────────────────────────────────

BASELINE_MODULES: dict[str, str] = {
    "bm25": "scripts.baselines.bm25",
    "mdpr": "scripts.baselines.mdpr",
    "mcontriever": "scripts.baselines.mcontriever",
    "me5": "scripts.baselines.me5",
    "bgem3": "scripts.baselines.bgem3",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MIRACL-ko 평가 코어 - Retriever baseline 을 지정해 평가 실행"
    )
    parser.add_argument(
        "--system",
        required=True,
        choices=list(BASELINE_MODULES.keys()),
        help="평가할 baseline 시스템명",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=100,
        help="검색 top-k (기본 100)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="passage encoding batch size (기본 32)",
    )
    parser.add_argument(
        "--split",
        default="dev",
        help="MIRACL-ko split (기본 dev)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="데이터 로드만 하고 평가 실행 안 함 (smoke test 용)",
    )
    args = parser.parse_args()

    # baseline 모듈 로드
    mod_name = BASELINE_MODULES[args.system]
    # sys.path 에 ROOT 추가 (scripts 패키지 인식)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    logger.info(f"baseline 모듈 로드: {mod_name}")
    try:
        mod = importlib.import_module(mod_name)
    except ImportError as exc:
        logger.error(f"baseline 모듈 로드 실패: {exc}")
        sys.exit(1)

    # baseline 임포트 후 RNG 재고정 — 일부 baseline 모듈이 import 시점에
    # 자체 RNG 호출을 일으킬 수 있으므로 retriever 생성 직전에 재시드.
    set_global_seed(GLOBAL_SEED)
    logger.info(f"global seed = {GLOBAL_SEED} (paper §V-E reproducibility)")

    retriever: Retriever = mod.get_retriever()
    if not isinstance(retriever, Retriever):
        logger.error(
            f"{mod_name}.get_retriever() 가 Retriever Protocol 을 만족하지 않습니다."
        )
        sys.exit(1)

    corpus, queries = load_miracl_ko(split=args.split)

    if args.dry_run:
        logger.info(
            f"[dry-run] corpus={len(corpus):,}, queries={len(queries):,} — 평가 스킵"
        )
        return

    result = evaluate(
        retriever=retriever,
        corpus=corpus,
        queries=queries,
        top_k=args.top_k,
        batch_size=args.batch_size,
        system_name=args.system,
    )
    out_path = save_result(result, args.system)
    print(f"\n결과 파일: {out_path}")
    print(json.dumps(result["aggregated"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
