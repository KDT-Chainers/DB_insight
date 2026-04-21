"""
파일 관련 유틸리티 API

GET  /api/files/indexed       — 인덱싱된 파일 목록 (전체 컬렉션 합산)
GET  /api/files/stats         — 타입별 청크 수 통계
GET  /api/files/detail?path=  — 특정 파일의 전체 청크 텍스트

※ /api/files/open, /api/files/open-folder 는 routes/search.py 에 있음
"""

import os

from flask import Blueprint, jsonify, request

files_bp = Blueprint("files", __name__, url_prefix="/api/files")


# ── 인덱싱된 파일 목록 ────────────────────────────────────

@files_bp.get("/indexed")
def indexed():
    """인덱싱된 모든 파일 목록 (파일별 청크 수 포함)."""
    from db.vector_store import get_indexed_files
    try:
        data = get_indexed_files()
        # 파일 크기·존재 여부 추가
        for item in data:
            fp = item["file_path"]
            try:
                stat = os.stat(fp)
                item["size"]   = stat.st_size
                item["exists"] = True
            except OSError:
                item["size"]   = None
                item["exists"] = False
        return jsonify({"files": data, "total": len(data)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── 타입별 통계 ──────────────────────────────────────────

@files_bp.get("/stats")
def stats():
    """타입별 파일 수·청크 수 통계."""
    from db.vector_store import get_indexed_files, count, COLLECTION_MAP
    try:
        all_files = get_indexed_files()
        by_type: dict[str, dict] = {}
        for t in COLLECTION_MAP:
            by_type[t] = {"file_count": 0, "chunk_count": 0}
        for f in all_files:
            t = f["file_type"]
            if t not in by_type:
                by_type[t] = {"file_count": 0, "chunk_count": 0}
            by_type[t]["file_count"]  += 1
            by_type[t]["chunk_count"] += f.get("chunk_count", 0)

        total_chunks = sum(v["chunk_count"] for v in by_type.values())
        total_files  = len(all_files)
        return jsonify({
            "by_type":      by_type,
            "total_files":  total_files,
            "total_chunks": total_chunks,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── 파일 상세 (전체 청크 텍스트) ─────────────────────────

@files_bp.get("/detail")
def detail():
    """
    GET /api/files/detail?path=C:/...

    해당 파일의 모든 청크 텍스트를 반환.
    video는 blip/stt 소스를 구분해서 반환.
    """
    file_path = request.args.get("path", "").strip()
    if not file_path:
        return jsonify({"error": "path is required"}), 400

    from db.vector_store import _get_collection, COLLECTION_MAP
    chunks: list[dict] = []
    file_type = None

    for t in COLLECTION_MAP:
        try:
            col = _get_collection(t)
            if col.count() == 0:
                continue
            res = col.get(
                where={"file_path": file_path},
                include=["metadatas"],
            )
            metas = res.get("metadatas") or []
            if metas:
                file_type = t
                for m in metas:
                    chunks.append({
                        "chunk_index":  m.get("chunk_index", 0),
                        "chunk_text":   m.get("chunk_text", ""),
                        "chunk_source": m.get("chunk_source", ""),  # video: blip|stt
                    })
        except Exception:
            continue

    if not chunks:
        return jsonify({"file_path": file_path, "file_type": file_type, "chunks": [], "full_text": ""})

    # 청크 순서 정렬
    chunks.sort(key=lambda c: (c.get("chunk_source", ""), c.get("chunk_index", 0)))

    # 중복 제거 (양방향 청킹으로 겹치는 텍스트 존재)
    seen: set[str] = set()
    unique: list[dict] = []
    for c in chunks:
        key = c["chunk_text"][:80]
        if key not in seen:
            seen.add(key)
            unique.append(c)

    # 전체 텍스트 조합
    if file_type == "video":
        blip_parts = [c["chunk_text"] for c in unique if c.get("chunk_source") == "blip"]
        stt_parts  = [c["chunk_text"] for c in unique if c.get("chunk_source") != "blip"]
        full_text = ""
        if blip_parts:
            full_text += "[프레임 캡션]\n" + " ".join(blip_parts)
        if stt_parts:
            if full_text:
                full_text += "\n\n"
            full_text += "[음성 텍스트]\n" + " ".join(stt_parts)
    else:
        full_text = " ".join(c["chunk_text"] for c in unique)

    return jsonify({
        "file_path": file_path,
        "file_type": file_type,
        "chunks":    unique,
        "full_text": full_text,
    })


# ── 파일 삭제 (ChromaDB에서 해당 파일 청크 전부 제거) ────────────

@files_bp.delete("/delete")
def delete():
    """
    DELETE /api/files/delete
    Body: { "file_path": "C:/..." }

    ChromaDB에서 해당 파일의 모든 청크를 삭제한다.
    원본 파일 자체는 건드리지 않는다.
    """
    data = request.get_json(silent=True) or {}
    file_path = data.get("file_path", "").strip()
    if not file_path:
        return jsonify({"error": "file_path is required"}), 400

    from db.vector_store import delete_file
    try:
        delete_file(file_path)
        return jsonify({"ok": True, "file_path": file_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


