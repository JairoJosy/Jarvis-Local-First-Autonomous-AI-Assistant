from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock

from jarvis.v2.reminders import ReminderOpsService
from jarvis.v2.schemas import ContextSnapshot, Recommendation


class ContextSenseService:
    def __init__(self, reminders: ReminderOpsService) -> None:
        self._reminders = reminders
        self._lock = Lock()
        self._latest = ContextSnapshot(
            timestamp=datetime.now(timezone.utc),
            weather_summary="Cloudy",
            temperature_c=27.0,
            is_rain_expected=False,
            traffic_summary="Moderate traffic",
            location_label="Unknown",
            style_profile="Smart casual",
            calendar_events=[],
            top_reminders=[],
        )

    def update_from_text(self, text: str) -> None:
        lowered = text.lower()
        with self._lock:
            snapshot = self._latest.model_copy(deep=True)
            snapshot.timestamp = datetime.now(timezone.utc)
            if "going out" in lowered or "go out" in lowered:
                snapshot.user_status = "going_out"
            if "rain" in lowered or "cloudy" in lowered:
                snapshot.is_rain_expected = True
                snapshot.weather_summary = "Cloudy with possible rain"
            if "meeting" in lowered:
                snapshot.calendar_events = ["Team meeting at 10:00", *snapshot.calendar_events][:3]
            self._latest = snapshot

    def snapshot(self) -> ContextSnapshot:
        with self._lock:
            snap = self._latest.model_copy(deep=True)
        snap.timestamp = datetime.now(timezone.utc)
        snap.top_reminders = self._reminders.top_reminders(limit=3)
        return snap

    def recommendations(self) -> list[Recommendation]:
        snap = self.snapshot()
        recs: list[Recommendation] = []

        if snap.calendar_events:
            recs.append(
                Recommendation(
                    category="meeting_prep",
                    message="You have a meeting today. Review agenda and prep key talking points.",
                    confidence=0.89,
                    rationale="Calendar event indicates a meeting; preparation improves outcomes.",
                    suggested_actions=["Open meeting notes", "Set 15-minute prep block"],
                    source_confidence=0.85,
                    verification_refs=["calendar_signal"],
                )
            )
            recs.append(
                Recommendation(
                    category="outfit",
                    message=f"Suggested attire: {snap.style_profile} with a polished layer for the meeting.",
                    confidence=0.78,
                    rationale="Meeting context plus style profile favors a polished presentation.",
                    suggested_actions=["Prepare outfit now", "Check weather before leaving"],
                    source_confidence=0.74,
                    verification_refs=["calendar_signal", "style_profile"],
                )
            )

        if snap.is_rain_expected or "rain" in snap.weather_summary.lower():
            recs.append(
                Recommendation(
                    category="weather",
                    message="Rain is possible. Carry an umbrella before heading out.",
                    confidence=0.92,
                    rationale="Weather context indicates possible precipitation.",
                    suggested_actions=["Pack umbrella", "Leave 10 minutes earlier"],
                    source_confidence=0.9,
                    verification_refs=["weather_signal"],
                )
            )

        if "heavy" in snap.traffic_summary.lower():
            recs.append(
                Recommendation(
                    category="commute",
                    message="Traffic looks heavy. Leave earlier to stay on schedule.",
                    confidence=0.84,
                    rationale="Traffic signal suggests likely delays.",
                    suggested_actions=["Start commute 15 minutes early"],
                    source_confidence=0.8,
                    verification_refs=["traffic_signal"],
                )
            )

        for reminder in snap.top_reminders[:2]:
            recs.append(
                Recommendation(
                    category="bill",
                    message=f"Upcoming bill reminder: {reminder}",
                    confidence=0.95,
                    rationale="Bill schedule indicates upcoming due date.",
                    suggested_actions=["Mark payment plan", "Pay early if possible"],
                    requires_confirmation=False,
                    source_confidence=0.93,
                    verification_refs=["bill_schedule"],
                )
            )

        if not recs:
            recs.append(
                Recommendation(
                    category="general",
                    message="No urgent context flags right now. Keep going with your top task.",
                    confidence=0.7,
                    rationale="No high-priority context events detected.",
                    suggested_actions=["Continue focused work", "Ask for next-step planning if needed"],
                    source_confidence=0.65,
                    verification_refs=["context_snapshot"],
                )
            )

        return recs
