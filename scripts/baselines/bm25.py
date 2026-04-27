"""scripts/baselines/bm25.py — BM25 (Pyserini/Anserini) baseline.

Pyserini 로 MIRACL-ko corpus 를 Anserini BM25 인덱스로 빌드 후 검색.
의존성: pyserini>=0.22, Java 11+

BM25 는 sparse retrieval 이므로 encode_passages / encode_query 는
실제 벡터를 반환하지 않는다 — search() 가 내부적으로 Lucene 을 호출.
numpy 인터페이스는 Protocol 호환을 위해 더미 반환.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
INDEX_DIR = ROOT / "Data" / "cache" / "miracl_ko" / "bm25_index"
CORPUS_JSONL = ROOT / "Data" / "cache" / "miracl_ko" / "corpus.jsonl"


def _check_java() -> None:
    """Java 가 설치되어 있는지 확인."""
    if shutil.which("java") is None:
        raise EnvironmentError(
            "Java 가 설치되어 있지 않습니다. "
            "Pyserini/Anserini 는 Java 11+ 가 필요합니다.\n"
            "  Ubuntu: sudo apt install default-jdk\n"
            "  macOS : brew install openjdk@11"
        )
    result = subprocess.run(
        ["java", "-version"], capture_output=True, text=True
    )
    logger.info(f"Java: {(result.stdout or result.stderr).splitlines()[0]}")


def _check_pyserini() -> Any:
    """pyserini import 확인."""
    try:
        from pyserini.search.lucene import LuceneSearcher  # type: ignore
        return LuceneSearcher
    except ImportError:
        raise ImportError(
            "pyserini 가 설치되어 있지 않습니다.\n"
            "  pip install pyserini>=0.22"
        )


def _write_corpus_jsonl(corpus: list[dict]) -> None:
    """Anserini 가 인식하는 JSONL 포맷으로 corpus 를 저장.

    Anserini collection format: {"id": ..., "contents": ...}
    """
    CORPUS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"corpus JSONL 작성 중 → {CORPUS_JSONL}")
    with CORPUS_JSONL.open("w", encoding="utf-8") as f:
        for doc in corpus:
            title = doc.get("title", "")
            text = doc.get("text", "")
            contents = (title + " " + text).strip() if title else text
            record = {"id": doc["docid"], "contents": contents}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info(f"corpus JSONL 작성 완료 — {CORPUS_JSONL}")


def _build_index() -> None:
    """Anserini IndexCollection 으로 BM25 인덱스 빌드."""
    if INDEX_DIR.exists() and any(INDEX_DIR.iterdir()):
        logger.info(f"기존 인덱스 재사용: {INDEX_DIR}")
        return

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"BM25 인덱스 빌드 시작 → {INDEX_DIR}")

    cmd = [
        "python", "-m", "pyserini.index.lucene",
        "--collection", "JsonCollection",
        "--input", str(CORPUS_JSONL.parent),
        "--index", str(INDEX_DIR),
        "--generator", "DefaultLuceneDocumentGenerator",
        "--threads", "4",
        "--storePositions",
        "--storeDocvectors",
        "--storeRaw",
        "--language", "ko",
    ]
    logger.info(f"인덱스 빌드 명령: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"인덱스 빌드 실패:\n{result.stderr}")
        raise RuntimeError(f"Anserini 인덱스 빌드 실패 (rc={result.returncode})")
    logger.info("인덱스 빌드 완료")


class BM25Retriever:
    """Pyserini LuceneSearcher 기반 BM25 Retriever.

    encode_passages / encode_query 는 Protocol 호환용 더미.
    실제 검색은 search() 내부에서 Lucene 을 직접 호출.
    """

    def __init__(self, k1: float = 0.9, b: float = 0.4) -> None:
        _check_java()
        LuceneSearcher = _check_pyserini()
        if not INDEX_DIR.exists():
            raise RuntimeError(
                f"BM25 인덱스가 없습니다: {INDEX_DIR}\n"
                "먼저 build_index(corpus) 를 호출하세요."
            )
        self._searcher = LuceneSearcher(str(INDEX_DIR))
        self._searcher.set_bm25(k1, b)
        logger.info(f"BM25Retriever 초기화 완료 (k1={k1}, b={b})")

        # docid → 순서 인덱스 매핑은 evaluate() 에서 passage_mat 대신
        # 내부 검색을 쓰므로 별도로 관리한다.
        self._docid_to_idx: dict[str, int] = {}

    def set_docid_map(self, docids: list[str]) -> None:
        """passage_mat 의 docid 순서를 등록 (search 결과 idx 반환용)."""
        self._docid_to_idx = {d: i for i, d in enumerate(docids)}

    def encode_passages(self, passages: list[str]) -> np.ndarray:
        """BM25 는 벡터 불필요 — 더미 zeros 반환 (Protocol 호환)."""
        return np.zeros((len(passages), 1), dtype=np.float32)

    def encode_query(self, query: str) -> np.ndarray:
        """BM25 는 벡터 불필요 — 쿼리 텍스트를 인스턴스에 저장."""
        self._last_query = query
        return np.zeros((1,), dtype=np.float32)

    def search(
        self,
        query_vec: np.ndarray,
        passage_mat: np.ndarray,
        top_k: int = 100,
    ) -> list[tuple[int, float]]:
        """Lucene BM25 검색. query_vec/passage_mat 은 무시하고 _last_query 사용."""
        query = getattr(self, "_last_query", "")
        if not query:
            return []
        hits = self._searcher.search(query, k=top_k)
        results: list[tuple[int, float]] = []
        for hit in hits:
            docid = hit.docid
            idx = self._docid_to_idx.get(docid, -1)
            if idx >= 0:
                results.append((idx, float(hit.score)))
        return results


# ── 외부 진입점 ────────────────────────────────────────────────────────────────


def build_index(corpus: list[dict]) -> None:
    """eval_miracl_ko.py 외부에서 인덱스 사전 빌드 시 호출."""
    _check_java()
    _check_pyserini()
    _write_corpus_jsonl(corpus)
    _build_index()


def get_retriever() -> BM25Retriever:
    """eval_miracl_ko.py 가 호출하는 표준 진입점.

    인덱스가 없으면 안내 메시지 후 종료.
    (build_index(corpus) 를 먼저 실행해야 한다.)
    """
    try:
        return BM25Retriever()
    except RuntimeError as exc:
        logger.error(str(exc))
        logger.error(
            "BM25 인덱스를 먼저 빌드하세요:\n"
            "  from scripts.baselines.bm25 import build_index\n"
            "  from scripts.eval_miracl_ko import load_miracl_ko\n"
            "  corpus, _ = load_miracl_ko()\n"
            "  build_index(corpus)"
        )
        sys.exit(1)
