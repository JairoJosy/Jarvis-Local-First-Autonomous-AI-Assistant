from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Iterator

from jarvis.schemas import EventFact, PersonFact
from jarvis.timezone_utils import safe_zoneinfo


def _canonicalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.strip().lower())


def _utc_and_local_iso(local_tz: str) -> tuple[str, str]:
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(safe_zoneinfo(local_tz))
    return now_utc.isoformat(), now_local.isoformat()


class StructuredMemoryStore:
    def __init__(self, db_path: Path, timezone_name: str) -> None:
        self._db_path = db_path
        self._tz = timezone_name
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
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS persons (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  canonical_name TEXT NOT NULL UNIQUE,
                  display_name TEXT NOT NULL,
                  profession TEXT,
                  location TEXT,
                  traits_json TEXT NOT NULL DEFAULT '[]',
                  aliases_json TEXT NOT NULL DEFAULT '[]',
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS person_aliases (
                  alias_norm TEXT PRIMARY KEY,
                  person_id INTEGER NOT NULL,
                  alias_text TEXT NOT NULL,
                  FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  event TEXT NOT NULL,
                  location TEXT,
                  description TEXT NOT NULL,
                  timestamp_utc TEXT NOT NULL,
                  timestamp_local TEXT NOT NULL,
                  source_turn_id TEXT
                );

                CREATE TABLE IF NOT EXISTS timeline (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  category TEXT NOT NULL,
                  summary TEXT NOT NULL,
                  details_json TEXT NOT NULL,
                  timestamp_utc TEXT NOT NULL,
                  timestamp_local TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS vector_memory (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  text TEXT NOT NULL,
                  ref_type TEXT NOT NULL,
                  ref_id INTEGER,
                  source_turn_id TEXT,
                  created_at_utc TEXT NOT NULL
                );
                """
            )

    def _find_person_id(
        self, conn: sqlite3.Connection, canonical_name: str, alias_norms: list[str]
    ) -> int | None:
        row = conn.execute(
            "SELECT id FROM persons WHERE canonical_name = ?",
            (canonical_name,),
        ).fetchone()
        if row:
            return int(row["id"])
        for alias_norm in alias_norms:
            alias_row = conn.execute(
                "SELECT person_id FROM person_aliases WHERE alias_norm = ?",
                (alias_norm,),
            ).fetchone()
            if alias_row:
                return int(alias_row["person_id"])
        return None

    def upsert_person(self, fact: PersonFact) -> dict[str, Any]:
        canonical = _canonicalize_name(fact.name)
        alias_candidates = [fact.name, *fact.aliases]
        alias_norms = sorted({_canonicalize_name(a) for a in alias_candidates if a.strip()})
        now_utc, _ = _utc_and_local_iso(self._tz)

        with self._lock:
            with self._conn() as conn:
                person_id = self._find_person_id(conn, canonical, alias_norms)

                if person_id is None:
                    conn.execute(
                        """
                        INSERT INTO persons (
                          canonical_name, display_name, profession, location, traits_json, aliases_json, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            canonical,
                            fact.name,
                            fact.profession,
                            fact.location,
                            json.dumps(sorted(set(fact.traits))),
                            json.dumps(sorted(set(alias_candidates))),
                            now_utc,
                        ),
                    )
                    person_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
                else:
                    row = conn.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()
                    existing_traits = set(json.loads(row["traits_json"]))
                    incoming_traits = {t.strip().lower() for t in fact.traits if t.strip()}
                    merged_traits = sorted(existing_traits | incoming_traits)

                    existing_aliases = set(json.loads(row["aliases_json"]))
                    incoming_aliases = {a.strip() for a in alias_candidates if a.strip()}
                    merged_aliases = sorted(existing_aliases | incoming_aliases)

                    profession = fact.profession.strip() if fact.profession else row["profession"]
                    location = fact.location.strip() if fact.location else row["location"]

                    conn.execute(
                        """
                        UPDATE persons
                        SET display_name = ?, profession = ?, location = ?, traits_json = ?, aliases_json = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            fact.name or row["display_name"],
                            profession,
                            location,
                            json.dumps(merged_traits),
                            json.dumps(merged_aliases),
                            now_utc,
                            person_id,
                        ),
                    )

                for alias in alias_candidates:
                    alias_text = alias.strip()
                    if not alias_text:
                        continue
                    alias_norm = _canonicalize_name(alias_text)
                    if not alias_norm:
                        continue
                    conn.execute(
                        """
                        INSERT INTO person_aliases (alias_norm, person_id, alias_text)
                        VALUES (?, ?, ?)
                        ON CONFLICT(alias_norm) DO UPDATE SET
                          person_id = excluded.person_id,
                          alias_text = excluded.alias_text
                        """,
                        (alias_norm, person_id, alias_text),
                    )

                final = conn.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()
                return self._person_row_to_dict(final)

    def get_person(self, name_or_alias: str) -> dict[str, Any] | None:
        normalized = _canonicalize_name(name_or_alias)
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM persons WHERE canonical_name = ?",
                    (normalized,),
                ).fetchone()
                if row:
                    return self._person_row_to_dict(row)
                alias_row = conn.execute(
                    "SELECT person_id FROM person_aliases WHERE alias_norm = ?",
                    (normalized,),
                ).fetchone()
                if not alias_row:
                    return None
                person_row = conn.execute(
                    "SELECT * FROM persons WHERE id = ?",
                    (int(alias_row["person_id"]),),
                ).fetchone()
                if person_row is None:
                    return None
                return self._person_row_to_dict(person_row)

    def search_people(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        text = query.strip().lower()
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM persons
                    WHERE lower(display_name) LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (f"%{text}%", limit),
                ).fetchall()
                return [self._person_row_to_dict(r) for r in rows]

    def add_event(self, fact: EventFact) -> int:
        timestamp = fact.timestamp or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        utc_iso = timestamp.astimezone(timezone.utc).isoformat()
        local_iso = timestamp.astimezone(safe_zoneinfo(self._tz)).isoformat()
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO events (event, location, description, timestamp_utc, timestamp_local, source_turn_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fact.event,
                        fact.location,
                        fact.description,
                        utc_iso,
                        local_iso,
                        fact.source_turn_id,
                    ),
                )
                row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
                return int(row["id"])

    def search_events(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        q = query.strip().lower()
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM events
                    WHERE lower(event) LIKE ? OR lower(location) LIKE ? OR lower(description) LIKE ?
                    ORDER BY timestamp_utc DESC
                    LIMIT ?
                    """,
                    (f"%{q}%", f"%{q}%", f"%{q}%", limit),
                ).fetchall()
                return [dict(r) for r in rows]

    def append_timeline(self, category: str, summary: str, details: dict[str, Any] | None = None) -> int:
        utc_iso, local_iso = _utc_and_local_iso(self._tz)
        payload = json.dumps(details or {})
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO timeline (category, summary, details_json, timestamp_utc, timestamp_local)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (category, summary, payload, utc_iso, local_iso),
                )
                row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
                return int(row["id"])

    def get_timeline(self, *, range_key: str, limit: int, local_tz: str) -> list[dict[str, Any]]:
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM timeline
                    ORDER BY timestamp_utc DESC
                    LIMIT ?
                    """,
                    (max(limit * 5, limit),),
                ).fetchall()
        items = [dict(r) for r in rows]
        if range_key == "today":
            today_local = datetime.now(safe_zoneinfo(local_tz)).date()
            filtered = []
            for item in items:
                local_ts = datetime.fromisoformat(item["timestamp_local"])
                if local_ts.date() == today_local:
                    filtered.append(item)
            return filtered[:limit]
        return items[:limit]

    def insert_vector_metadata(
        self, *, text: str, ref_type: str, ref_id: int | None, source_turn_id: str
    ) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO vector_memory (text, ref_type, ref_id, source_turn_id, created_at_utc)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (text, ref_type, ref_id, source_turn_id, created_at),
                )
                row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
                return int(row["id"])

    def get_vector_metadata(self, ids: list[int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    f"SELECT * FROM vector_memory WHERE id IN ({placeholders})",
                    tuple(ids),
                ).fetchall()
        by_id = {int(r["id"]): dict(r) for r in rows}
        return [by_id[idx] for idx in ids if idx in by_id]

    def _person_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "name": row["display_name"],
            "profession": row["profession"],
            "location": row["location"],
            "traits": json.loads(row["traits_json"]),
            "aliases": json.loads(row["aliases_json"]),
            "updated_at": row["updated_at"],
        }
