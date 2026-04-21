import os
import subprocess

from flask import Blueprint, jsonify, request

search_bp = Blueprint("search", __name__, url_prefix="/api")


# ── 검색 ──────────────────────────────────────────────────────────

@search_bp.get("/search")
def search():
    """
    GET /api/search?q=검색어&top_k=10&type=doc|image|audio|video

    type 미지정 → 인덱싱된 모든 타입에서 검색 후 유사도 합산.

    Response:
    {
      "query": "검색어",
      "results": [
        {
          "file_path":  str,
          "file_name":  str,
          "file_type":  str,   # doc | image | audio | video
          "similarity": float, # 0.0 ~ 1.0
          "snippet":    str
        },
        ...
      ]
    }
    """
    query     = request.args.get("q", "").strip()
    top_k     = request.args.get("top_k", default=10, type=int)
    file_type = request.args.get("type", default=None)

    if not query:
        return jsonify({"error": "q is required"}), 400
    if top_k <= 0:
        top_k = 10

    try:
        from db.vector_store import search as vs_search, search_all, search_video_m11, count

        if count() == 0:
            return jsonify({"query": query, "results": []})

        if file_type:
            # 특정 타입만 검색
            if file_type == "video":
                from embedders.base import encode_query_e5
                query_vec = encode_query_e5(query)
                results   = search_video_m11(query_vec, top_k=top_k)
            else:
                query_vec = _encode_for_type(query, file_type)
                results   = vs_search(query_vec, file_type=file_type, top_k=top_k)
        else:
            # 모든 타입 검색 — 타입별 인코딩 후 합산
            embeddings_by_type = _encode_all(query)
            results = search_all(embeddings_by_type, top_k=top_k)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"query": query, "results": results})


def _encode_for_type(query: str, file_type: str) -> list[float]:
    """파일 타입에 맞는 모델로 쿼리 인코딩."""
    if file_type == "audio":
        from embedders.base import encode_query_ko
        return encode_query_ko(query)
    elif file_type == "video":
        from embedders.base import encode_query_e5
        return encode_query_e5(query)
    else:
        from embedders.base import encode_query
        return encode_query(query)


def _encode_all(query: str) -> dict[str, list[float]]:
    """
    각 타입별 모델로 쿼리를 인코딩.
      doc/image → 384d (MiniLM)
      audio     → 768d (ko-sroberta)
      video     → 1024d (e5-large, M11)
    각 컬렉션에 청크가 없으면 포함하지 않음.
    """
    from db.vector_store import count as col_count

    result: dict[str, list[float] | None] = {}

    # 384d 모델 (doc, image)
    if col_count("doc") > 0 or col_count("image") > 0:
        from embedders.base import encode_query
        vec_mini = encode_query(query)
        if col_count("doc")   > 0: result["doc"]   = vec_mini
        if col_count("image") > 0: result["image"] = vec_mini

    # 768d 모델 (audio)
    if col_count("audio") > 0:
        from embedders.base import encode_query_ko
        vec_ko = encode_query_ko(query)
        result["audio"] = vec_ko

    # 1024d 모델 (video, M11 e5-large)
    if col_count("video") > 0:
        from embedders.base import encode_query_e5
        vec_e5 = encode_query_e5(query)
        result["video"] = vec_e5

    return result


# ── 인덱싱된 파일 목록 ────────────────────────────────────────────

@search_bp.get("/indexed-files")
def indexed_files():
    """GET /api/indexed-files"""
    try:
        from db.vector_store import get_indexed_files, count
        files = get_indexed_files()
        return jsonify({"total_chunks": count(), "files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── 파일 열기 ─────────────────────────────────────────────────────

@search_bp.post("/files/open")
def file_open():
    """POST /api/files/open  body: { "file_path": "C:/..." }"""
    data      = request.get_json(silent=True) or {}
    file_path = data.get("file_path", "")
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404
    os.startfile(file_path)
    return jsonify({"success": True})


@search_bp.post("/files/open-folder")
def folder_open():
    """POST /api/files/open-folder  body: { "file_path": "C:/..." }"""
    data      = request.get_json(silent=True) or {}
    file_path = data.get("file_path", "")
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404
    subprocess.Popen(["explorer", "/select,", file_path])
    return jsonify({"success": True})
