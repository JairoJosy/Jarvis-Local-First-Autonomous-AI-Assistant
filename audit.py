from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Iterator

from jarvis.schemas import TurnAuditRecord


class AuditLogger:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = Lock()
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  turn_id TEXT NOT NULL,
                  session_id TEXT NOT NULL,
                  payload_json TEXT NOT NULL
                )
                """
            )

    def log_turn(self, record: TurnAuditRecord) -> None:
        payload = json.dumps(record.model_dump(mode="json"))
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_logs (turn_id, session_id, payload_json)
                    VALUES (?, ?, ?)
                    """,
                    (record.turn_id, record.session_id, payload),
                )

