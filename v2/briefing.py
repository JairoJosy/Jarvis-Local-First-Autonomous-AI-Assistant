from __future__ import annotations

from datetime import datetime, timezone

from jarvis.v2.context import ContextSenseService
from jarvis.v2.schemas import MorningBriefing


class BriefingService:
    def __init__(self, context_service: ContextSenseService) -> None:
        self._context = context_service

    def today(self) -> MorningBriefing:
        context = self._context.snapshot()
        recommendations = self._context.recommendations()

        highlights = []
        if context.calendar_events:
            highlights.append(f"Meetings: {', '.join(context.calendar_events[:2])}")
        highlights.append(f"Weather: {context.weather_summary}")
        if context.top_reminders:
            highlights.append(f"Top reminder: {context.top_reminders[0]}")
        highlights.append(f"Traffic: {context.traffic_summary}")

        summary = "Morning briefing ready: priorities, weather, commute, and reminders."
        return MorningBriefing(
            summary=summary,
            highlights=highlights,
            recommendations=recommendations,
            generated_at=datetime.now(timezone.utc),
        )

