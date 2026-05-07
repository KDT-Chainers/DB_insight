"""인덱싱 UI 의 '이미 임베딩됨' 배지용 lookup 엔드포인트.

/api/registry/check 에 절대경로 리스트를 POST 하면 도메인 registry.json
4개를 조회하여 각 경로의 인덱싱 여부를 반환한다.
"""
from flask import Blueprint, request, jsonify

from services.registry_lookup import lookup, orphans_under

registry_bp = Blueprint("registry", __name__, url_prefix="/api/registry")

_MAX_BATCH = 5000


@registry_bp.post("/check")
def check():
    """POST /api/registry/check
    Body:     { "paths": ["C:\\...\\file.pdf", ...] }
    Response: { "results": { "<path>": { "indexed": bool, "domain": str|None }, ... } }
    """
    data = request.get_json(silent=True) or {}
    paths = data.get("paths", [])
    if not isinstance(paths, list):
        return jsonify({"error": "paths must be a list"}), 400
    if len(paths) > _MAX_BATCH:
        return jsonify({"error": f"too many paths (max {_MAX_BATCH})"}), 400
    return jsonify({"results": lookup(paths)})


@registry_bp.post("/orphans")
def orphans():
    """POST /api/registry/orphans
    임베딩 후 사용자가 raw_DB 에서 삭제한 파일(=registry 에는 있지만 disk 에 없음).
    Body:     { "path": "C:\\...\\raw_DB\\Doc" }
    Response: { "count": int, "orphans": [{ "path": str, "domain": str }, ...] }
    """
    data = request.get_json(silent=True) or {}
    folder_path = (data.get("path") or "").strip()
    if not folder_path:
        return jsonify({"error": "path is required"}), 400
    items = orphans_under(folder_path)
    return jsonify({"count": len(items), "orphans": items})
