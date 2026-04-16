from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from db.init_db import get_connection


history_bp = Blueprint("history", __name__, url_prefix="/api/history")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@history_bp.get("")
def get_history():
    limit = request.args.get("limit", default=50, type=int)
    if limit is None or limit <= 0:
        limit = 50

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, query, method, result_count, searched_at
            FROM search_history
            ORDER BY searched_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    history = [
        {
            "id": row["id"],
            "query": row["query"],
            "method": row["method"],
            "result_count": row["result_count"],
            "searched_at": row["searched_at"],
        }
        for row in rows
    ]
    return jsonify({"history": history})


@history_bp.post("")
def add_history():
    # Internal-only endpoint: this is for backend auto-calls after search execution.
    # Frontend must not call this endpoint directly.
    data = request.get_json(silent=True) or {}
    query = data.get("query")
    method = data.get("method")
    result_count = data.get("result_count")

    if not isinstance(query, str) or not query:
        return jsonify({"error": "Invalid query"}), 400
    if method is not None and not isinstance(method, str):
        return jsonify({"error": "Invalid method"}), 400
    if result_count is not None and not isinstance(result_count, int):
        return jsonify({"error": "Invalid result_count"}), 400

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO search_history (query, method, result_count, searched_at)
            VALUES (?, ?, ?, ?)
            """,
            (query, method, result_count, utc_now_iso()),
        )
        conn.commit()

    return jsonify({"id": cursor.lastrowid})


@history_bp.delete("")
def delete_all_history():
    with get_connection() as conn:
        conn.execute("DELETE FROM search_history")
        conn.commit()
    return jsonify({"success": True})


@history_bp.delete("/<int:history_id>")
def delete_history_item(history_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM search_history WHERE id = ?", (history_id,))
        conn.commit()
    return jsonify({"success": True})
