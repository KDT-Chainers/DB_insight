"""
vectordb/store.py
──────────────────────────────────────────────────────────────────────────────
단일 FAISS 인덱스 벡터 DB.

설계 원칙 (리팩토링 후):
  - 원문 텍스트를 그대로 임베딩·저장한다 (마스킹 손실 없음 → 검색 품질 유지)
  - PII 여부·유형은 메타데이터 태그로만 관리한다
  - UI 렌더링 단계에서만 마스킹/모자이크를 적용한다 (저장 데이터 불변)
  - display_masked 플래그: True이면 UI가 해당 청크를 마스킹 표시함

이전 HybridVectorStore(3개 인덱스) 구조를 제거하고 단일 인덱스로 단순화했다.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

import config
from document.chunker import Chunk


def _to_python(obj):
    """
    numpy scalar / ndarray 를 JSON 직렬화 가능한 순수 파이썬 타입으로 재귀 변환.
    EasyOCR bbox 좌표(numpy.int32/float32)를 json.dumps 전에 처리하기 위해 사용.
    """
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, list):
        return [_to_python(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_to_python(v) for v in obj)
    if isinstance(obj, dict):
        return {k: _to_python(v) for k, v in obj.items()}
    return obj

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 임베딩 모델 (싱글턴)
# ──────────────────────────────────────────────────────────────────────────────

_embedding_model = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("임베딩 모델 로딩: %s", config.EMBEDDING_MODEL)
        _embedding_model = SentenceTransformer(config.EMBEDDING_MODEL)
    return _embedding_model


_PII_KR_MAP = {
    "KR_RRN":            "주민등록번호 주민번호",
    "KR_PASSPORT":       "여권 여권번호 passport",
    "KR_DRIVER_LICENSE": "운전면허 면허증",
    "KR_BANK_ACCOUNT":   "계좌번호 통장 은행",
    "KR_BRN":            "사업자번호 사업자등록증",
}


def _pii_types_to_korean(pii_types: List[str]) -> str:
    """
    PII 유형 리스트를 한국어 검색 키워드 문자열로 변환한다.
    전화·이메일 등은 임베딩 보강에 쓰지 않는다(정책 비대상).
    """
    from security.pii_filter_helpers import POLICY_PROTECTED_PII_TYPES

    keywords: List[str] = []
    for t in pii_types:
        if str(t).upper() not in POLICY_PROTECTED_PII_TYPES:
            continue
        kw = _PII_KR_MAP.get(t)
        if kw:
            keywords.append(kw)
    return " ".join(keywords)


def embed_texts(texts: List[str]) -> np.ndarray:
    """
    텍스트 목록을 L2 정규화된 임베딩 벡터로 변환. Shape: (N, D)

    정규화 이유:
      SBERT는 코사인 유사도 기반으로 학습됐다.
      벡터를 단위 구면으로 정규화하면 내적(IndexFlatIP) = 코사인 유사도가 되어
      검색 순위가 의미적으로 올바르게 계산된다.
      L2 거리(IndexFlatL2)를 쓰면 418 같은 무의미한 숫자가 나오고 랭킹도 틀린다.
    """
    model = _get_embedding_model()
    embeddings = model.encode(
        texts,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,   # 단위 벡터로 정규화 → cosine similarity 가능
    )
    return embeddings.astype("float32")


# ──────────────────────────────────────────────────────────────────────────────
# VectorStore
# ──────────────────────────────────────────────────────────────────────────────

class VectorStore:
    """
    단일 FAISS 인덱스 + SQLite 메타데이터 저장소.

    변경 사항 (v2):
      - 원문 텍스트 그대로 저장 (마스킹 저장 제거)
      - has_pii / pii_types / sensitivity_score / display_masked 컬럼 추가
      - display_masked: True이면 UI 카드에서 마스킹 표시 (저장 데이터는 원문 유지)

    사용법:
        store = VectorStore()
        store.add_chunks(chunks, pii_metadata={0: {"has_pii": True, ...}})
        results = store.search("여권 번호", top_k=5)
    """

    def __init__(self, store_dir: Path = config.VECTOR_DIR) -> None:
        self._dir        = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "faiss.index"
        self._meta_db    = self._dir / "meta.db"
        self._index      = None
        self._chunk_ids: List[int] = []
        self._version_file = self._dir / "_index_version.txt"

        self._init_db()
        self._migrate_schema()
        self._check_index_version()   # L2 → IP 마이그레이션 처리
        self._load_if_exists()

    # ── 스키마 초기화 / 마이그레이션 ────────────────────────────────────────────

    def _init_db(self) -> None:
        """SQLite 메타 테이블 생성"""
        with sqlite3.connect(self._meta_db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_name          TEXT,
                    source_page       INTEGER,
                    chunk_index       INTEGER,
                    start_char        INTEGER,
                    end_char          INTEGER,
                    text              TEXT,
                    source_path       TEXT    DEFAULT '',
                    file_name         TEXT    DEFAULT '',
                    bbox              TEXT    DEFAULT NULL,
                    has_pii           INTEGER DEFAULT 0,
                    pii_types         TEXT    DEFAULT '[]',
                    sensitivity_score REAL    DEFAULT 0.0,
                    display_masked    INTEGER DEFAULT 0,
                    is_image          INTEGER DEFAULT 0,
                    image_path        TEXT    DEFAULT '',
                    pii_regions       TEXT    DEFAULT '[]',
                    content_sha256    TEXT    DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_state (
                    k TEXT PRIMARY KEY,
                    v TEXT NOT NULL
                )
            """)
            conn.commit()

    def _migrate_schema(self) -> None:
        """
        이전 스키마(masked 컬럼 등)에서 신규 컬럼이 없으면 추가한다.
        기존 데이터는 보존하고 새 컬럼은 기본값으로 채운다.
        """
        new_cols = {
            "source_path":       "TEXT    DEFAULT ''",
            "file_name":         "TEXT    DEFAULT ''",
            "bbox":              "TEXT    DEFAULT NULL",
            "has_pii":           "INTEGER DEFAULT 0",
            "pii_types":         "TEXT    DEFAULT '[]'",
            "sensitivity_score": "REAL    DEFAULT 0.0",
            "display_masked":    "INTEGER DEFAULT 0",
            "is_image":          "INTEGER DEFAULT 0",
            "image_path":        "TEXT    DEFAULT ''",
            "pii_regions":       "TEXT    DEFAULT '[]'",
            "content_sha256":    "TEXT    DEFAULT ''",
        }
        with sqlite3.connect(self._meta_db) as conn:
            existing = {row[1] for row in conn.execute("PRAGMA table_info(chunks)")}
            for col, col_def in new_cols.items():
                if col not in existing:
                    conn.execute(f"ALTER TABLE chunks ADD COLUMN {col} {col_def}")
            conn.commit()

    _CURRENT_INDEX_VERSION = "cosine_v1"   # IndexFlatIP + normalized

    def _check_index_version(self) -> None:
        """
        이전에 IndexFlatL2로 저장된 인덱스가 있으면 자동으로 삭제하고
        새 버전(IndexFlatIP + cosine)으로 재구축을 유도한다.

        버전 파일이 없거나 버전이 다르면 기존 faiss.index를 제거한다.
        → 사용자가 문서를 다시 임베딩해야 올바른 코사인 유사도가 저장된다.
        """
        version = ""
        if self._version_file.exists():
            version = self._version_file.read_text().strip()

        if version != self._CURRENT_INDEX_VERSION:
            if self._index_path.exists():
                self._index_path.unlink()
                logger.warning(
                    "인덱스 버전 불일치 (기존: %r, 신규: %r) → 기존 FAISS 인덱스 삭제. "
                    "문서를 다시 임베딩해주세요.",
                    version,
                    self._CURRENT_INDEX_VERSION,
                )
            self._version_file.write_text(self._CURRENT_INDEX_VERSION)

    def _load_if_exists(self) -> None:
        """저장된 FAISS 인덱스가 있으면 로드"""
        if self._index_path.exists():
            import faiss
            self._index = faiss.read_index(str(self._index_path))
            with sqlite3.connect(self._meta_db) as conn:
                rows = conn.execute("SELECT id FROM chunks ORDER BY id").fetchall()
                self._chunk_ids = [r[0] for r in rows]
            logger.info("VectorStore 로드: %d 청크", len(self._chunk_ids))

    # ── 청크 추가 ─────────────────────────────────────────────────────────────

    def has_content_sha256(self, sha256_hex: str) -> bool:
        """
        동일 바이트 내용의 문서가 이미 인덱스에 있는지 확인한다.
        (각 청크 행에 동일 해시가 저장되므로 한 행만 있어도 True)
        """
        if not sha256_hex or not sha256_hex.strip():
            return False
        with sqlite3.connect(self._meta_db) as conn:
            row = conn.execute(
                "SELECT 1 FROM chunks WHERE content_sha256 = ? LIMIT 1",
                (sha256_hex.strip(),),
            ).fetchone()
        return row is not None

    def set_recent_upload_keys(self, keys: List[str]) -> None:
        """최근 업로드 문서 식별자 목록을 영구 저장한다."""
        clean = [k.strip() for k in keys if isinstance(k, str) and k.strip()]
        val = json.dumps(list(dict.fromkeys(clean)), ensure_ascii=False)
        with sqlite3.connect(self._meta_db) as conn:
            conn.execute(
                """
                INSERT INTO app_state(k, v) VALUES(?, ?)
                ON CONFLICT(k) DO UPDATE SET v=excluded.v
                """,
                ("recent_upload_keys", val),
            )
            conn.commit()

    def get_recent_upload_keys(self) -> List[str]:
        """영구 저장된 최근 업로드 문서 식별자 목록을 읽는다."""
        with sqlite3.connect(self._meta_db) as conn:
            row = conn.execute(
                "SELECT v FROM app_state WHERE k=?",
                ("recent_upload_keys",),
            ).fetchone()
        if not row or not row[0]:
            return []
        try:
            data = json.loads(row[0])
            if isinstance(data, list):
                return [str(x) for x in data if str(x).strip()]
        except Exception:
            logger.warning("recent_upload_keys 파싱 실패, 빈 목록으로 처리")
        return []

    def add_chunks(
        self,
        chunks: List[Chunk],
        pii_metadata: Optional[Dict[int, Dict[str, Any]]] = None,
        content_sha256: str = "",
    ) -> None:
        """
        청크 원문을 그대로 임베딩하여 저장한다.
        PII 정보는 별도 메타데이터 태그로만 기록한다.

        Args:
            chunks:       저장할 청크 리스트 (원문 텍스트 — 마스킹하지 않음)
            pii_metadata: {chunk.index: {"has_pii", "pii_types", "sensitivity_score",
                          "display_masked"}} 형태의 PII 태그 dict.
                          해당 청크가 UI에서 마스킹 표시되어야 하면 display_masked=True.
            content_sha256: 업로드 원본 파일 SHA-256(hex). 중복 검사·추적용.
        """
        if not chunks:
            return

        pii_meta = pii_metadata or {}
        sha_val = (content_sha256 or "").strip()

        # ── 임베딩용 텍스트 보강 ──────────────────────────────────────────────
        # 원문은 그대로 DB에 저장하고, 임베딩에는 파일명·PII유형 키워드를 앞에 붙여
        # 파일명이 "스크린샷.jpg"처럼 의미 없어도 PII 유형으로 검색 가능하게 한다.
        embed_texts_list = []
        for c in chunks:
            meta = pii_meta.get(c.index, {})
            pii_types: List[str] = meta.get("pii_types", [])

            # PII 유형 → 한국어 키워드 변환
            pii_kr = _pii_types_to_korean(pii_types)

            file_name = Path(c.source_path).name if c.source_path else c.doc_name
            prefix_parts = []
            if file_name:
                prefix_parts.append(f"[파일: {file_name}]")
            if pii_kr:
                prefix_parts.append(f"[문서유형: {pii_kr}]")

            prefix = " ".join(prefix_parts)
            embed_text = f"{prefix}\n{c.text}".strip() if prefix else c.text
            embed_texts_list.append(embed_text)

        embeddings = embed_texts(embed_texts_list)

        import faiss
        if self._index is None:
            dim = embeddings.shape[1]
            # IndexFlatIP + 정규화 벡터 = 코사인 유사도 (0~1, 클수록 유사)
            self._index = faiss.IndexFlatIP(dim)
            logger.info("FAISS 인덱스 생성 (IndexFlatIP cosine, dim=%d)", dim)

        self._index.add(embeddings)

        with sqlite3.connect(self._meta_db) as conn:
            for chunk in chunks:
                meta    = pii_meta.get(chunk.index, {})
                has_pii = 1 if meta.get("has_pii", False) else 0
                pt_json = json.dumps(meta.get("pii_types", []), ensure_ascii=False)
                score   = float(meta.get("sensitivity_score", 0.0))
                display_masked = 1 if meta.get("display_masked", False) else 0
                bbox_json = json.dumps(_to_python(chunk.bbox)) if chunk.bbox else None
                file_name = Path(chunk.source_path).name if chunk.source_path else chunk.doc_name

                is_image   = 1 if meta.get("is_image", False) else 0
                image_path = meta.get("image_path", "") or ""
                # EasyOCR bbox 좌표가 numpy.int32일 수 있으므로 순수 파이썬 타입으로 변환
                pii_regions_json = json.dumps(
                    _to_python(meta.get("pii_regions", [])), ensure_ascii=False
                )

                cursor = conn.execute(
                    """INSERT INTO chunks
                       (doc_name, source_page, chunk_index, start_char, end_char,
                        text, source_path, file_name, bbox,
                        has_pii, pii_types, sensitivity_score, display_masked,
                        is_image, image_path, pii_regions, content_sha256)
                       VALUES (?, ?, ?, ?, ?,
                               ?, ?, ?, ?,
                               ?, ?, ?, ?,
                               ?, ?, ?, ?)""",
                    (
                        chunk.doc_name,
                        chunk.source_page,
                        chunk.index,
                        chunk.start_char,
                        chunk.end_char,
                        chunk.text,
                        chunk.source_path or "",
                        file_name,
                        bbox_json,
                        has_pii,
                        pt_json,
                        score,
                        display_masked,
                        is_image,
                        image_path,
                        pii_regions_json,
                        sha_val,
                    ),
                )
                self._chunk_ids.append(cursor.lastrowid)
            conn.commit()

        self._save_index()
        logger.info("%d 청크 저장 완료 (원문 임베딩)", len(chunks))

    # ── 검색 ─────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = config.TOP_K,
    ) -> List[Dict[str, Any]]:
        """
        쿼리와 가장 유사한 청크를 반환한다.

        Returns:
            List[{id, doc_name, source_page, text, source_path, file_name,
                  bbox, has_pii, pii_types, sensitivity_score,
                  display_masked, score}]
        """
        if self._index is None or self._index.ntotal == 0:
            logger.warning("VectorStore 비어 있음")
            return []

        query_vec = embed_texts([query])
        distances, indices = self._index.search(query_vec, min(top_k, self._index.ntotal))

        results: List[Dict[str, Any]] = []
        with sqlite3.connect(self._meta_db) as conn:
            for dist, idx in zip(distances[0], indices[0]):
                if idx < 0 or idx >= len(self._chunk_ids):
                    continue
                db_id = self._chunk_ids[int(idx)]
                row = conn.execute(
                    """SELECT id, doc_name, source_page, chunk_index, start_char, text,
                              source_path, file_name, bbox,
                              has_pii, pii_types, sensitivity_score, display_masked,
                              is_image, image_path, pii_regions
                       FROM chunks WHERE id=?""",
                    (db_id,),
                ).fetchone()
                if row:
                    # IndexFlatIP + 정규화 벡터 → dist = 코사인 유사도 (0~1)
                    cosine_sim = max(0.0, min(1.0, float(dist)))
                    results.append({
                        "id":                row[0],
                        "doc_name":          row[1],
                        "source_page":       row[2],
                        "chunk_index":       row[3],
                        "start_char":        row[4],
                        "text":              row[5],
                        "source_path":       row[6] or "",
                        "file_name":         row[7] or row[1] or "",
                        "bbox":              json.loads(row[8]) if row[8] else None,
                        "has_pii":           bool(row[9]),
                        "pii_types":         json.loads(row[10]) if row[10] else [],
                        "sensitivity_score": float(row[11]),
                        "display_masked":    bool(row[12]),
                        "is_image":          bool(row[13]),
                        "image_path":        row[14] or "",
                        "pii_regions":       json.loads(row[15]) if row[15] else [],
                        "score":             cosine_sim,
                    })
        return results

    def search_within_doc(
        self,
        query: str,
        doc_name_hint: str,
        top_k: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        doc_name / file_name / source_path 에 hint 문자열이 포함된
        청크만 대상으로 검색한다.

        일반 search()와 달리 FAISS 전체 검색 후 SQL 필터로 좁히는 방식.
        문서명을 질문에서 명시했을 때 다른 문서와 섞이는 것을 방지한다.
        """
        if self._index is None or self._index.ntotal == 0:
            return []
        hint = doc_name_hint.strip().lower()
        if not hint:
            return self.search(query, top_k=top_k)

        # FAISS는 전체 대상으로 넉넉하게 검색 (힌트 문서가 하위에 있을 수 있으므로)
        search_k = min(self._index.ntotal, max(top_k * 6, 120))
        query_vec = embed_texts([query])
        distances, indices = self._index.search(query_vec, search_k)

        results: List[Dict[str, Any]] = []
        with sqlite3.connect(self._meta_db) as conn:
            for dist, idx in zip(distances[0], indices[0]):
                if idx < 0 or idx >= len(self._chunk_ids):
                    continue
                db_id = self._chunk_ids[int(idx)]
                row = conn.execute(
                    """SELECT id, doc_name, source_page, chunk_index, start_char, text,
                              source_path, file_name, bbox,
                              has_pii, pii_types, sensitivity_score, display_masked,
                              is_image, image_path, pii_regions
                       FROM chunks WHERE id=?""",
                    (db_id,),
                ).fetchone()
                if not row:
                    continue
                # 힌트가 doc_name / file_name / source_path 중 하나에라도 포함되면 포함
                candidate = " ".join([
                    (row[1] or ""),
                    (row[7] or ""),
                    (row[6] or ""),
                ]).lower()
                import re as _re
                cand_norm = _re.sub(r"[^0-9a-z가-힣]", "", candidate)
                hint_norm = _re.sub(r"[^0-9a-z가-힣]", "", hint)
                if hint_norm not in cand_norm:
                    continue
                cosine_sim = max(0.0, min(1.0, float(dist)))
                results.append({
                    "id":                row[0],
                    "doc_name":          row[1],
                    "source_page":       row[2],
                    "chunk_index":       row[3],
                    "start_char":        row[4],
                    "text":              row[5],
                    "source_path":       row[6] or "",
                    "file_name":         row[7] or row[1] or "",
                    "bbox":              json.loads(row[8]) if row[8] else None,
                    "has_pii":           bool(row[9]),
                    "pii_types":         json.loads(row[10]) if row[10] else [],
                    "sensitivity_score": float(row[11]),
                    "display_masked":    bool(row[12]),
                    "is_image":          bool(row[13]),
                    "image_path":        row[14] or "",
                    "pii_regions":       json.loads(row[15]) if row[15] else [],
                    "score":             cosine_sim,
                })
                if len(results) >= top_k:
                    break
        logger.info(
            "[VectorStore] search_within_doc hint=%r → %d청크", hint, len(results)
        )
        return results

    def list_doc_names(self) -> List[str]:
        """저장된 모든 문서의 doc_name 목록을 반환한다."""
        with sqlite3.connect(self._meta_db) as conn:
            rows = conn.execute(
                "SELECT DISTINCT COALESCE(file_name, doc_name) FROM chunks WHERE COALESCE(file_name, doc_name) != ''"
            ).fetchall()
        return [r[0] for r in rows if r[0]]

    def build_feature_map(
        self,
        results: List[Dict[str, Any]],
        user_query: str,
    ) -> Dict[str, Any]:
        """
        검색 결과 + 쿼리를 기반으로 Feature Map 생성.
        실제 청크 원문은 포함하지 않음 — 보안 에이전트에 전달할 메타데이터만 포함.
        """
        from security.pii_filter_helpers import (
            filter_to_protected_pii_types,
            sensitivity_from_protected_types,
        )

        pii_types: List[str] = []
        for r in results:
            for t in filter_to_protected_pii_types(r.get("pii_types") or []):
                if t not in pii_types:
                    pii_types.append(t)

        contains_pii = any(
            bool(filter_to_protected_pii_types(r.get("pii_types") or []))
            for r in results
        )

        protected_hits = sum(
            1 for r in results
            if filter_to_protected_pii_types(r.get("pii_types") or [])
        )
        pii_chunk_ratio = round(
            protected_hits / max(len(results), 1),
            4,
        )

        bulk_keywords = ["전부", "모두", "전체", "all", "dump", "export"]
        bulk_request  = any(kw in user_query.lower() for kw in bulk_keywords)

        # 검색 결과별 민감도는 보호 대상 PII만 반영해 재계산
        max_score = 0.0
        for r in results:
            pts = filter_to_protected_pii_types(r.get("pii_types") or [])
            max_score = max(max_score, sensitivity_from_protected_types(pts))
        sensitivity_score = max_score
        if bulk_request:
            sensitivity_score = min(1.0, sensitivity_score + 0.4)

        return {
            "matched_docs":      len(results),
            "contains_pii":      contains_pii,
            "pii_types":         pii_types,
            "pii_chunk_ratio":   pii_chunk_ratio,
            "bulk_request":      bulk_request,
            "owner_match":       True,
            "sensitivity_score": round(sensitivity_score, 4),
        }

    # ── 영구 저장 / 초기화 ────────────────────────────────────────────────────

    def _save_index(self) -> None:
        if self._index is not None:
            import faiss
            faiss.write_index(self._index, str(self._index_path))

    def clear(self) -> None:
        """인덱스와 메타데이터 초기화 (테스트용)"""
        self._index     = None
        self._chunk_ids = []
        if self._index_path.exists():
            self._index_path.unlink()
        with sqlite3.connect(self._meta_db) as conn:
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM app_state WHERE k='recent_upload_keys'")
            conn.commit()
        logger.info("VectorStore 초기화 완료")


# 하위 호환 별칭
HybridVectorStore = VectorStore
