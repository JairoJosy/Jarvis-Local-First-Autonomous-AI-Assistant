from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from jarvis.v2.radar import RiskOpportunityRadarService
from jarvis.v2.reminders import ReminderOpsService
from jarvis.v2.schemas import RadarScanRequest, SchedulerEvent, SchedulerStatus


class BackgroundSchedulerService:
    def __init__(
        self,
        *,
        db_path: Path,
        reminders: ReminderOpsService,
        radar: RiskOpportunityRadarService,
        interval_seconds: int = 300,
    ) -> None:
        self._db_path = db_path
        self._reminders = reminders
        self._radar = radar
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._status = SchedulerStatus(running=False, interval_seconds=interval_seconds)
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
                CREATE TABLE IF NOT EXISTS v2_scheduler_events (
                  event_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                )
                """
            )

    def start(self, *, interval_seconds: int | None = None) -> SchedulerStatus:
        with self._lock:
            if interval_seconds:
                self._interval_seconds = interval_seconds
                self._status.interval_seconds = interval_seconds
            if self._status.running:
                return self._status.model_copy(deep=True)
            self._stop.clear()
            self._status.running = True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            return self._status.model_copy(deep=True)

    def stop(self) -> SchedulerStatus:
        self._stop.set()
        with self._lock:
            self._status.running = False
            return self._status.model_copy(deep=True)

    def status(self) -> SchedulerStatus:
        with self._lock:
            self._status.events_recorded = len(self.list_events(limit=1000))
            return self._status.model_copy(deep=True)

    def run_once(self) -> SchedulerStatus:
        self._run_once()
        return self.status()

    def list_events(self, *, limit: int = 100) -> list[SchedulerEvent]:
        with self._conn() as conn:
            rows = conn.execute("SELECT payload_json FROM v2_scheduler_events").fetchall()
        events = [SchedulerEvent.model_validate(json.loads(row["payload_json"])) for row in rows]
        events.sort(key=lambda event: event.created_at, reverse=True)
        return events[:limit]

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._run_once()
            self._stop.wait(self._interval_seconds)
        with self._lock:
            self._status.running = False

    def _run_once(self) -> None:
        try:
            for occurrence in self._reminders.due_notifications():
                self._record(
                    SchedulerEvent(
                        event_id=uuid4().hex[:12],
                        event_type="bill_notification",
                        summary=f"Bill reminder due: {occurrence.bill_name}",
                        payload=occurrence.model_dump(mode="json"),
                        created_at=datetime.now(timezone.utc),
                    )
                )
            radar = self._radar.scan(RadarScanRequest(session_id="scheduler", context_text=""))
            if radar.findings:
                self._record(
                    SchedulerEvent(
                        event_id=uuid4().hex[:12],
                        event_type="radar_scan",
                        summary=radar.summary,
                        payload=radar.model_dump(mode="json"),
                        created_at=datetime.now(timezone.utc),
                    )
                )
            with self._lock:
                self._status.last_run_at = datetime.now(timezone.utc)
                self._status.last_error = None
        except Exception as exc:
            event = SchedulerEvent(
                event_id=uuid4().hex[:12],
                event_type="error",
                summary=f"Scheduler run failed: {exc}",
                payload={"error": str(exc)},
                created_at=datetime.now(timezone.utc),
            )
            self._record(event)
            with self._lock:
                self._status.last_error = str(exc)

    def _record(self, event: SchedulerEvent) -> None:
        payload = json.dumps(event.model_dump(mode="json"))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_scheduler_events (event_id, payload_json)
                VALUES (?, ?)
                """,
                (event.event_id, payload),
            )
