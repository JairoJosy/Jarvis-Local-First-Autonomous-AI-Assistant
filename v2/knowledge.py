from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Iterator
from uuid import uuid4

from jarvis.v2.schemas import KnowledgeArtifact, KnowledgeCaptureRequest


class KnowledgeDocService:
    """
    Personal knowledge + auto-doc capture.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = Lock()
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS v2_knowledge_artifacts (
                  artifact_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                )
                """
            )

    def capture(self, request: KnowledgeCaptureRequest) -> KnowledgeArtifact:
        artifact = KnowledgeArtifact(
            artifact_id=uuid4().hex[:12],
            session_id=request.session_id,
            source=request.source,
            title=request.title,
            content=request.content,
            tags=request.tags,
            summary=self._summarize(request.content),
            searchable_tokens=self._tokenize(request.title + " " + request.content),
            created_at=datetime.now(timezone.utc),
        )
        self._save(artifact)
        return artifact

    def list_notes(self, *, session_id: str | None = None, q: str | None = None, limit: int = 30) -> list[KnowledgeArtifact]:
        with self._conn() as conn:
            rows = conn.execute("SELECT payload_json FROM v2_knowledge_artifacts").fetchall()
        items = [KnowledgeArtifact.model_validate(json.loads(r["payload_json"])) for r in rows]
        if session_id:
            items = [i for i in items if i.session_id == session_id]
        if q:
            q_tokens = set(self._tokenize(q))
            items = [i for i in items if q_tokens.intersection(i.searchable_tokens)]
        items.sort(key=lambda i: i.created_at, reverse=True)
        return items[:limit]

    def _save(self, artifact: KnowledgeArtifact) -> None:
        payload = json.dumps(artifact.model_dump(mode="json"))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_knowledge_artifacts (artifact_id, payload_json)
                VALUES (?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (artifact.artifact_id, payload),
            )

    def _summarize(self, content: str) -> str:
        stripped = " ".join(content.split())
        if len(stripped) <= 180:
            return stripped
        return stripped[:177] + "..."

    def _tokenize(self, text: str) -> list[str]:
        return list(dict.fromkeys(re.findall(r"[a-z0-9_]{3,}", text.lower())))

