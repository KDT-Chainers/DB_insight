import os
import subprocess

from flask import Blueprint, jsonify, request

search_bp = Blueprint("search", __name__, url_prefix="/api")

# ---------------------------------------------------------------------------
# 검색기 플레이스홀더
# 팀원 검색기 완성 시 아래 함수를 실제 모듈로 교체
#
# 각 함수 반환 규칙:
#   - 검색기 없음(미구현): None
#   - 검색 성공: list[dict]  ← 아래 SearchResult 구조 참고
#
# SearchResult 구조:
#   {
#     "file_id":   str,   # 파일 고유 ID
#     "file_name": str,   # 파일명 (확장자 포함)
#     "similarity": float, # 0.0 ~ 1.0
#     "snippet":   str,   # 검색어 주변 텍스트
#   }
# ---------------------------------------------------------------------------


def _search_doc(query: str, top_k: int):
    return None  # TODO: 팀원 doc 검색기 연결


def _search_video(query: str, top_k: int):
    return None  # TODO: 팀원 video 검색기 연결


def _search_image(query: str, top_k: int):
    return None  # TODO: 팀원 image 검색기 연결


def _search_audio(query: str, top_k: int):
    return None  # TODO: 팀원 audio 검색기 연결


SEARCHERS = {
    "doc":   _search_doc,
    "video": _search_video,
    "image": _search_image,
    "audio": _search_audio,
}


# ---------------------------------------------------------------------------
# 파일 경로 조회 헬퍼
# 팀원 검색기 완성 시 file_id → 절대 경로 변환 로직 구현
# ---------------------------------------------------------------------------

def _get_file_path(file_id: str) -> str | None:
    # TODO: ChromaDB 메타데이터에서 file_id → path 조회
    return None


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------

@search_bp.get("/search")
def search():
    """
    GET /api/search?q=검색어&top_k=10

    Response:
    {
      "query": "검색어",
      "results": {
        "doc":   { "available": true,  "items": [ SearchResult, ... ] },
        "video": { "available": false, "items": [] },
        "image": { "available": true,  "items": [ SearchResult, ... ] },
        "audio": { "available": false, "items": [] }
      }
    }
    """
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "q is required"}), 400

    top_k = request.args.get("top_k", default=10, type=int)
    if top_k <= 0:
        top_k = 10

    results = {}
    for type_name, searcher_fn in SEARCHERS.items():
        try:
            items = searcher_fn(query, top_k)
            if items is None:
                results[type_name] = {"available": False, "items": []}
            else:
                results[type_name] = {"available": True, "items": items}
        except Exception:
            results[type_name] = {"available": False, "items": []}

    return jsonify({"query": query, "results": results})


@search_bp.get("/files/<file_id>")
def file_detail(file_id: str):
    """
    GET /api/files/{file_id}

    Response:
    {
      "file_id":         str,
      "file_name":       str,
      "file_type":       str,   # doc / video / image / audio
      "file_path":       str,
      "folder_path":     str,
      "content_preview": str
    }
    """
    # TODO: ChromaDB 메타데이터에서 file_id 기반 상세 정보 조회
    return jsonify({"error": "Not implemented"}), 501


@search_bp.post("/files/<file_id>/open")
def file_open(file_id: str):
    """POST /api/files/{file_id}/open — OS 기본 앱으로 파일 열기"""
    file_path = _get_file_path(file_id)
    if not file_path:
        return jsonify({"error": "File not found"}), 404
    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    os.startfile(file_path)
    return jsonify({"success": True})


@search_bp.post("/files/<file_id>/open-folder")
def folder_open(file_id: str):
    """POST /api/files/{file_id}/open-folder — 파일 탐색기로 해당 폴더 열기"""
    file_path = _get_file_path(file_id)
    if not file_path:
        return jsonify({"error": "File not found"}), 404
    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    subprocess.Popen(["explorer", "/select,", file_path])
    return jsonify({"success": True})
