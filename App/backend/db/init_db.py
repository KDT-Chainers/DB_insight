import sqlite3
import sys
import os
from pathlib import Path


def _get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        # PyInstaller 빌드: __file__은 매번 다른 임시 폴더 → APPDATA에 영구 저장
        app_data = os.environ.get('APPDATA') or os.environ.get('LOCALAPPDATA') or Path.home()
        return Path(app_data) / 'DB_insight'
    else:
        # 개발 환경: 소스 옆에 저장
        return Path(__file__).resolve().parent


BASE_DIR = _get_base_dir()
DB_PATH = BASE_DIR / "app.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(
            """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query        TEXT NOT NULL,
    method       TEXT,
    result_count INTEGER,
    searched_at  TEXT NOT NULL
);
"""
        )
