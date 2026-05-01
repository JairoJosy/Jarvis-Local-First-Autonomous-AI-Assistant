from __future__ import annotations

import calendar
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Iterator
from uuid import uuid4

from jarvis.v2.schemas import (
    BillProfile,
    BillProfileCreate,
    BillReminderOccurrence,
    BillReminderState,
    MarkBillPaidRequest,
)


@dataclass
class BillCycle:
    due_date: date
    lead_day: int
    notify_on: date


class ReminderOpsService:
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
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS v2_bill_profiles (
                  bill_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS v2_bill_payments (
                  payment_id TEXT PRIMARY KEY,
                  bill_id TEXT NOT NULL,
                  cycle_due_date TEXT NOT NULL,
                  paid_at_utc TEXT NOT NULL,
                  note TEXT
                );

                CREATE TABLE IF NOT EXISTS v2_bill_notifications (
                  notification_id TEXT PRIMARY KEY,
                  bill_id TEXT NOT NULL,
                  cycle_due_date TEXT NOT NULL,
                  lead_day INTEGER NOT NULL,
                  notified_at_utc TEXT NOT NULL
                );
                """
            )

    def create_bill_profile(self, payload: BillProfileCreate) -> BillProfile:
        now = datetime.now(timezone.utc)
        profile = BillProfile(
            bill_id=uuid4().hex[:12],
            name=payload.name,
            due_day=payload.due_day,
            due_date=payload.due_date,
            lead_days=sorted(set(payload.lead_days), reverse=True),
            amount=payload.amount,
            currency=payload.currency,
            channels=payload.channels,
            notes=payload.notes,
            active=True,
            created_at=now,
            updated_at=now,
        )
        self._save_profile(profile)
        return profile

    def list_bill_profiles(self) -> list[BillProfile]:
        with self._conn() as conn:
            rows = conn.execute("SELECT payload_json FROM v2_bill_profiles").fetchall()
        profiles = [BillProfile.model_validate(json.loads(row["payload_json"])) for row in rows]
        return sorted(profiles, key=lambda p: p.created_at)

    def get_bill_profile(self, bill_id: str) -> BillProfile | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM v2_bill_profiles WHERE bill_id = ?",
                (bill_id,),
            ).fetchone()
        if row is None:
            return None
        return BillProfile.model_validate(json.loads(row["payload_json"]))

    def mark_bill_paid(self, bill_id: str, payload: MarkBillPaidRequest) -> dict[str, str]:
        profile = self.get_bill_profile(bill_id)
        if profile is None:
            raise KeyError(f"Bill profile {bill_id} not found.")
        cycle_due_date = payload.cycle_due_date or self._next_due_date(profile, date.today())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_bill_payments (payment_id, bill_id, cycle_due_date, paid_at_utc, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex[:12],
                    bill_id,
                    cycle_due_date.isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    payload.note,
                ),
            )
        return {"bill_id": bill_id, "cycle_due_date": cycle_due_date.isoformat(), "status": "paid"}

    def upcoming_occurrences(self, within_days: int = 35) -> list[BillReminderOccurrence]:
        today = date.today()
        horizon = today + timedelta(days=max(0, within_days))
        occurrences: list[BillReminderOccurrence] = []
        for profile in self.list_bill_profiles():
            cycles = self._cycles_for_window(profile, today, horizon)
            for cycle in cycles:
                state = self._state_for_cycle(profile.bill_id, cycle.due_date, cycle.lead_day, today)
                occurrences.append(
                    BillReminderOccurrence(
                        reminder_id=f"{profile.bill_id}:{cycle.due_date.isoformat()}:{cycle.lead_day}",
                        bill_id=profile.bill_id,
                        bill_name=profile.name,
                        due_date=cycle.due_date,
                        notify_on=cycle.notify_on,
                        lead_day=cycle.lead_day,
                        state=state,
                        channels=profile.channels,
                    )
                )
        occurrences.sort(key=lambda item: (item.notify_on, item.bill_name))
        return occurrences

    def due_notifications(self) -> list[BillReminderOccurrence]:
        today = date.today()
        items = []
        for occurrence in self.upcoming_occurrences(within_days=40):
            if occurrence.notify_on <= today and occurrence.state == BillReminderState.SCHEDULED:
                items.append(occurrence)
                self._record_notification(occurrence.bill_id, occurrence.due_date, occurrence.lead_day)
        return items

    def top_reminders(self, limit: int = 3) -> list[str]:
        reminders: list[str] = []
        for occurrence in self.upcoming_occurrences(within_days=14):
            if occurrence.state in {BillReminderState.SCHEDULED, BillReminderState.OVERDUE}:
                reminders.append(
                    f"{occurrence.bill_name}: due {occurrence.due_date.isoformat()} "
                    f"(lead {occurrence.lead_day}d)"
                )
            if len(reminders) >= limit:
                break
        return reminders

    def _save_profile(self, profile: BillProfile) -> None:
        payload = json.dumps(profile.model_dump(mode="json"))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_bill_profiles (bill_id, payload_json)
                VALUES (?, ?)
                ON CONFLICT(bill_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (profile.bill_id, payload),
            )

    def _next_due_date(self, profile: BillProfile, ref_date: date) -> date:
        due_day = profile.due_day if profile.due_day is not None else profile.due_date.day  # type: ignore[union-attr]
        year, month = ref_date.year, ref_date.month
        last_day = calendar.monthrange(year, month)[1]
        d = min(due_day, last_day)
        candidate = date(year, month, d)
        if candidate >= ref_date:
            return candidate
        month += 1
        if month > 12:
            year += 1
            month = 1
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, min(due_day, last_day))

    def _cycles_for_window(self, profile: BillProfile, start: date, end: date) -> list[BillCycle]:
        due_dates: list[date] = []
        first_due = self._next_due_date(profile, start)
        due_dates.append(first_due)
        # Include one more cycle if horizon crosses next month.
        next_month = self._next_due_date(profile, first_due + timedelta(days=1))
        if next_month <= end:
            due_dates.append(next_month)

        cycles: list[BillCycle] = []
        for due_date in due_dates:
            for lead_day in sorted(set(profile.lead_days), reverse=True):
                notify_on = due_date - timedelta(days=max(0, lead_day))
                if notify_on > end:
                    continue
                cycles.append(BillCycle(due_date=due_date, lead_day=lead_day, notify_on=notify_on))
        return cycles

    def _state_for_cycle(self, bill_id: str, due_date: date, lead_day: int, today: date) -> BillReminderState:
        if self._is_paid(bill_id, due_date):
            return BillReminderState.PAID
        if today > due_date:
            return BillReminderState.OVERDUE
        if self._already_notified(bill_id, due_date, lead_day):
            return BillReminderState.NOTIFIED
        return BillReminderState.SCHEDULED

    def _is_paid(self, bill_id: str, due_date: date) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM v2_bill_payments
                WHERE bill_id = ? AND cycle_due_date = ?
                LIMIT 1
                """,
                (bill_id, due_date.isoformat()),
            ).fetchone()
        return row is not None

    def _already_notified(self, bill_id: str, due_date: date, lead_day: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM v2_bill_notifications
                WHERE bill_id = ? AND cycle_due_date = ? AND lead_day = ?
                LIMIT 1
                """,
                (bill_id, due_date.isoformat(), lead_day),
            ).fetchone()
        return row is not None

    def _record_notification(self, bill_id: str, due_date: date, lead_day: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_bill_notifications (notification_id, bill_id, cycle_due_date, lead_day, notified_at_utc)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex[:12],
                    bill_id,
                    due_date.isoformat(),
                    lead_day,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

