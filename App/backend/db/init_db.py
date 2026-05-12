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

-- [v3 aimode] 채팅방 메타데이터.
-- thread_id = LangGraph thread + AIMODE 채팅방 식별자.
CREATE TABLE IF NOT EXISTS aimode_threads (
    thread_id   TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '새 대화',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    msg_count   INTEGER NOT NULL DEFAULT 0,
    first_query TEXT
);

CREATE INDEX IF NOT EXISTS idx_aimode_threads_updated
    ON aimode_threads(updated_at DESC);

-- [v3 aimode] 채팅 메시지 누적 저장 — sidebar 클릭 시 history 복원에 사용.
-- _fallback_history 는 in-memory 라 백엔드 재시작 시 휘발 → SQLite 영속.
CREATE TABLE IF NOT EXISTS aimode_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id  TEXT NOT NULL,
    role       TEXT NOT NULL,         -- 'user' | 'assistant'
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    -- 답변 메타 (옵션) — turn 복원 시 references / sources 도 같이 표시 가능
    extra      TEXT,                  -- JSON: {sources, references, ...}
    FOREIGN KEY (thread_id) REFERENCES aimode_threads(thread_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_aimode_messages_thread
    ON aimode_messages(thread_id, id);
"""
        )
