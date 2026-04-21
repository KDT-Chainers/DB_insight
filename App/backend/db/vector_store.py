"""
ChromaDB 벡터 저장소 래퍼

타입별 독립 ChromaDB 인스턴스 (경로/차원이 다르기 때문에 분리)

  embedded_DB/Movie/ — files_video  (1024d, e5-large, M11)
  embedded_DB/Doc/   — files_doc    (384d,  MiniLM)
  embedded_DB/Img/   — files_image  (384d,  MiniLM)
  embedded_DB/Rec/   — files_audio  (768d,  ko-sroberta)

메타데이터 스키마 (청크 1개 = 레코드 1개)
  file_path    : str   — 원본 파일 절대 경로
  file_name    : str   — 파일명 (확장자 포함)
  file_type    : str   — doc | image | audio | video
  chunk_index  : int   — 0-based
  chunk_text   : str   — snippet 용 원문 (최대 300자)
  chunk_source : str   — (video 전용) "blip" | "stt"
  blip_weight  : float — (video 전용) 해당 영상의 BLIP 가중치
  stt_weight   : float — (video 전용) 해당 영상의 STT  가중치
"""

from __future__ import annotations

import chromadb
from chromadb.config import Settings

from config import (
    EMBEDDED_DB_VIDEO,
    EMBEDDED_DB_DOC,
    EMBEDDED_DB_IMAGE,
    EMBEDDED_DB_AUDIO,
)

# ── 타입별 DB 경로 매핑 ───────────────────────────────────────────
_DB_PATH_MAP: dict[str, object] = {
    "video": EMBEDDED_DB_VIDEO,
    "doc":   EMBEDDED_DB_DOC,
    "image": EMBEDDED_DB_IMAGE,
    "audio": EMBEDDED_DB_AUDIO,
}

# 타입별 컬렉션 이름
COLLECTION_MAP: dict[str, str] = {
    "video": "files_video",
    "doc":   "files_doc",
    "image": "files_image",
    "audio": "files_audio",
}

# ── 클라이언트 / 컬렉션 캐시 ─────────────────────────────────────
_clients: dict[str, chromadb.PersistentClient] = {}
_collections: dict[str, object] = {}


def _get_client(file_type: str) -> chromadb.PersistentClient:
    """file_type 별 독립 ChromaDB 클라이언트."""
    if file_type not in _clients:
        db_path = _DB_PATH_MAP.get(file_type)
        if db_path is None:
            # 알 수 없는 타입은 기본 경로
            from config import EMBEDDED_DB
            db_path = EMBEDDED_DB / file_type
            db_path.mkdir(parents=True, exist_ok=True)
        _clients[file_type] = chromadb.PersistentClient(
            path=str(db_path),
            settings=Settings(anonymized_telemetry=False),
        )
    return _clients[file_type]


def _get_collection(file_type: str):
    """file_type → ChromaDB 컬렉션 (없으면 생성)."""
    col_name = COLLECTION_MAP.get(file_type, f"files_{file_type}")
    key = f"{file_type}:{col_name}"
    if key not in _collections:
        client = _get_client(file_type)
        _collections[key] = client.get_or_create_collection(
            name=col_name,
            metadata={"hnsw:space": "cosine"},
        )
    return _collections[key]


# ── 공개 API ─────────────────────────────────────────────────────

def upsert_chunks(
    ids: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> None:
    """
    청크 임베딩을 벡터 저장소에 저장/덮어쓰기.
    metadatas 의 file_type 으로 컬렉션을 자동 선택.
    """
    if not ids:
        return
    file_type = metadatas[0].get("file_type", "doc")
    col = _get_collection(file_type)
    col.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas)


def delete_file(file_path: str, file_type: str | None = None) -> None:
    """
    특정 파일의 모든 청크를 삭제 (재인덱싱 전 호출).
    file_type 을 알면 해당 컬렉션만, 모르면 전체 컬렉션 스캔.
    """
    types = [file_type] if file_type else list(COLLECTION_MAP.keys())
    for t in types:
        try:
            col = _get_collection(t)
            col.delete(where={"file_path": file_path})
        except Exception:
            pass


def search(
    query_embedding: list[float],
    file_type: str,
    top_k: int = 10,
) -> list[dict]:
    """
    단일 컬렉션(file_type) 유사도 검색.
    파일 단위 집계 (같은 파일의 여러 청크 → 최대 유사도).

    반환: [{ file_path, file_name, file_type, similarity, snippet }, ...]
    """
    col = _get_collection(file_type)
    total = col.count()
    if total == 0:
        return []

    n = min(top_k * 5, total)
    results = col.query(
        query_embeddings=[query_embedding],
        n_results=n,
        include=["metadatas", "distances"],
    )

    raw_metas = results["metadatas"][0]
    raw_dists = results["distances"][0]

    best: dict[str, dict] = {}
    for meta, dist in zip(raw_metas, raw_dists):
        fp  = meta["file_path"]
        sim = round(1.0 - dist, 4)
        if fp not in best or sim > best[fp]["similarity"]:
            best[fp] = {
                "file_path": fp,
                "file_name": meta["file_name"],
                "file_type": meta["file_type"],
                "similarity": sim,
                "snippet":   meta.get("chunk_text", "")[:200],
            }

    return sorted(best.values(), key=lambda x: x["similarity"], reverse=True)[:top_k]


def search_video_m11(
    query_embedding: list[float],
    top_k: int = 10,
) -> list[dict]:
    """
    M11 방식 동영상 검색 (e5-large 1024d).

    동작:
      1. embedded_DB/Movie/ 컬렉션에서 충분히 많은 청크 조회
      2. 파일별 blip 청크 max 유사도(blip_score) / stt 청크 max 유사도(stt_score) 집계
      3. 최종 = blip_weight × blip_score + stt_weight × stt_score
    """
    col   = _get_collection("video")
    total = col.count()
    if total == 0:
        return []

    n = min(total, max(top_k * 30, 200))
    results = col.query(
        query_embeddings=[query_embedding],
        n_results=n,
        include=["metadatas", "distances"],
    )

    raw_metas = results["metadatas"][0]
    raw_dists = results["distances"][0]

    file_scores: dict[str, dict] = {}
    for meta, dist in zip(raw_metas, raw_dists):
        fp     = meta["file_path"]
        source = meta.get("chunk_source", "stt")
        sim    = max(0.0, round(1.0 - dist, 6))

        if fp not in file_scores:
            file_scores[fp] = {
                "file_path":    fp,
                "file_name":    meta["file_name"],
                "blip_score":   0.0,
                "stt_score":    0.0,
                "blip_snippet": "",
                "stt_snippet":  "",
                "blip_weight":  float(meta.get("blip_weight", 0.5)),
                "stt_weight":   float(meta.get("stt_weight",  0.5)),
            }

        if source == "blip":
            if sim > file_scores[fp]["blip_score"]:
                file_scores[fp]["blip_score"]   = sim
                file_scores[fp]["blip_snippet"]  = meta.get("chunk_text", "")[:200]
        else:
            if sim > file_scores[fp]["stt_score"]:
                file_scores[fp]["stt_score"]   = sim
                file_scores[fp]["stt_snippet"]  = meta.get("chunk_text", "")[:200]

    out: list[dict] = []
    for d in file_scores.values():
        bw    = d["blip_weight"]
        sw    = d["stt_weight"]
        final = round(bw * d["blip_score"] + sw * d["stt_score"], 4)
        snippet = (
            d["blip_snippet"]
            if d["blip_score"] >= d["stt_score"]
            else d["stt_snippet"]
        )
        out.append({
            "file_path":  d["file_path"],
            "file_name":  d["file_name"],
            "file_type":  "video",
            "similarity": final,
            "snippet":    snippet,
        })

    return sorted(out, key=lambda x: x["similarity"], reverse=True)[:top_k]


def search_all(
    embeddings_by_type: dict[str, list[float]],
    top_k: int = 10,
) -> list[dict]:
    """
    여러 컬렉션을 한 번에 검색하고 전체 유사도 기준으로 병합.

    embeddings_by_type = {
        "doc":   [384d],   "image": [384d],
        "audio": [768d],   "video": [1024d],
    }
    """
    all_results: list[dict] = []
    for file_type, emb in embeddings_by_type.items():
        if emb is None:
            continue
        if file_type == "video":
            hits = search_video_m11(emb, top_k=top_k)
        else:
            hits = search(emb, file_type=file_type, top_k=top_k)
        all_results.extend(hits)

    best: dict[str, dict] = {}
    for item in all_results:
        fp = item["file_path"]
        if fp not in best or item["similarity"] > best[fp]["similarity"]:
            best[fp] = item

    return sorted(best.values(), key=lambda x: x["similarity"], reverse=True)[:top_k]


def count(file_type: str | None = None) -> int:
    """저장된 전체 청크 수 (file_type 없으면 모든 컬렉션 합산)."""
    if file_type:
        return _get_collection(file_type).count()
    total = 0
    for t in COLLECTION_MAP:
        try:
            total += _get_collection(t).count()
        except Exception:
            pass
    return total


def get_indexed_files() -> list[dict]:
    """인덱싱된 파일 목록 (모든 컬렉션 합산)."""
    file_map: dict[str, dict] = {}
    for t in COLLECTION_MAP:
        try:
            col = _get_collection(t)
            if col.count() == 0:
                continue
            all_metas = col.get(include=["metadatas"])["metadatas"]
            for m in all_metas:
                fp = m["file_path"]
                if fp not in file_map:
                    file_map[fp] = {
                        "file_path":   fp,
                        "file_name":   m["file_name"],
                        "file_type":   m["file_type"],
                        "chunk_count": 0,
                    }
                file_map[fp]["chunk_count"] += 1
        except Exception:
            pass
    return list(file_map.values())
