"""
audit/logger.py
──────────────────────────────────────────────────────────────────────────────
감사 로그 저장.

저장 항목:
  - 업로드 시간, 파일명, 탐지된 개인정보 유형, 사용자 선택
  - 질문 유형(label), 차단 여부
  - 검색 문서 ID, 전체 보기 요청 여부

SQLite 에 저장 (data/audit.db).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    감사 이벤트를 SQLite 에 기록하는 싱글턴 스타일 클래스.

    사용법:
        audit = AuditLogger()
        audit.log_upload(filename="test.pdf", pii_types=["KR_RRN"], user_choice="mask_and_embed")
        audit.log_query(query="요약해줘", label="NORMAL", blocked=False)
    """

    def __init__(self, db_path: Path = config.AUDIT_DB) -> None:
        self._db = Path(db_path)
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── 스키마 초기화 ─────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS upload_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT NOT NULL,
                    filename    TEXT,
                    pii_types   TEXT,   -- JSON 배열
                    user_choice TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS query_events (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT NOT NULL,
                    query_text      TEXT,
                    label           TEXT,
                    action          TEXT,
                    blocked         INTEGER,
                    retrieved_ids   TEXT,   -- JSON 배열
                    full_view_req   INTEGER DEFAULT 0
                )
            """)
            conn.commit()

    # ── 업로드 이벤트 ─────────────────────────────────────────────────────────

    def log_upload(
        self,
        filename: str,
        pii_types: List[str],
        user_choice: str,
    ) -> None:
        """파일 업로드 + 사용자 선택 기록"""
        ts = datetime.now().isoformat(timespec="seconds")
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "INSERT INTO upload_events (timestamp, filename, pii_types, user_choice) VALUES (?,?,?,?)",
                (ts, filename, json.dumps(pii_types, ensure_ascii=False), user_choice),
            )
            conn.commit()
        logger.debug("감사 기록 [업로드] %s → %s", filename, user_choice)

    # ── 질문 이벤트 ───────────────────────────────────────────────────────────

    def log_query(
        self,
        query_text: str,
        label: str,
        action: str,
        blocked: bool,
        retrieved_ids: Optional[List[int]] = None,
        full_view_requested: bool = False,
    ) -> None:
        """질문 분류 결과 + 차단 여부 기록"""
        ts = datetime.now().isoformat(timespec="seconds")
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                """INSERT INTO query_events
                   (timestamp, query_text, label, action, blocked, retrieved_ids, full_view_req)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    ts,
                    query_text[:500],   # 너무 긴 쿼리는 잘라서 저장
                    label,
                    action,
                    1 if blocked else 0,
                    json.dumps(retrieved_ids or []),
                    1 if full_view_requested else 0,
                ),
            )
            conn.commit()
        logger.debug("감사 기록 [질문] label=%s blocked=%s", label, blocked)

    # ── 조회 ─────────────────────────────────────────────────────────────────

    def recent_uploads(self, limit: int = 20) -> List[Dict[str, Any]]:
        """최근 업로드 이벤트 조회"""
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(
                "SELECT timestamp, filename, pii_types, user_choice FROM upload_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"timestamp": r[0], "filename": r[1],
             "pii_types": json.loads(r[2]), "user_choice": r[3]}
            for r in rows
        ]

    def recent_queries(self, limit: int = 20) -> List[Dict[str, Any]]:
        """최근 질문 이벤트 조회"""
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(
                "SELECT timestamp, query_text, label, action, blocked FROM query_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"timestamp": r[0], "query": r[1],
             "label": r[2], "action": r[3], "blocked": bool(r[4])}
            for r in rows
        ]
