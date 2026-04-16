import hashlib
import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from db.init_db import get_connection


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
MASTER_PASSWORD_KEY = "master_password_hash"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_password_hash(password: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
    return f"{salt}:{digest}"


def verify_password(stored_value: str, password: str) -> bool:
    try:
        salt, stored_digest = stored_value.split(":", 1)
    except ValueError:
        return False
    digest = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
    return digest == stored_digest


def get_master_password_row():
    with get_connection() as conn:
        return conn.execute(
            "SELECT key, value, updated_at FROM settings WHERE key = ?",
            (MASTER_PASSWORD_KEY,),
        ).fetchone()


@auth_bp.get("/status")
def auth_status():
    row = get_master_password_row()
    return jsonify({"initialized": row is not None})


@auth_bp.post("/setup")
def auth_setup():
    data = request.get_json(silent=True) or {}
    password = data.get("password")
    if not isinstance(password, str) or not password:
        return jsonify({"error": "Invalid password"}), 400

    if get_master_password_row() is not None:
        return jsonify({"error": "Already initialized"}), 400

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (MASTER_PASSWORD_KEY, make_password_hash(password), utc_now_iso()),
        )
        conn.commit()
    return jsonify({"success": True})


@auth_bp.post("/verify")
def auth_verify():
    data = request.get_json(silent=True) or {}
    password = data.get("password")
    if not isinstance(password, str) or not password:
        return jsonify({"error": "Invalid password"}), 401

    row = get_master_password_row()
    if row is None or not verify_password(row["value"], password):
        return jsonify({"error": "Invalid password"}), 401
    return jsonify({"success": True})


@auth_bp.post("/reset")
def auth_reset():
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password")
    new_password = data.get("new_password")

    if (
        not isinstance(current_password, str)
        or not current_password
        or not isinstance(new_password, str)
        or not new_password
    ):
        return jsonify({"error": "Invalid current password"}), 401

    row = get_master_password_row()
    if row is None or not verify_password(row["value"], current_password):
        return jsonify({"error": "Invalid current password"}), 401

    with get_connection() as conn:
        conn.execute(
            "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?",
            (make_password_hash(new_password), utc_now_iso(), MASTER_PASSWORD_KEY),
        )
        conn.commit()
    return jsonify({"success": True})
