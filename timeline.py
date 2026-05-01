from __future__ import annotations

from typing import Any

from jarvis.memory.structured import StructuredMemoryStore


class TimelineService:
    def __init__(self, structured_store: StructuredMemoryStore, timezone_name: str) -> None:
        self._structured = structured_store
        self._tz = timezone_name

    def get_activity(self, *, range_key: str, limit: int = 10) -> list[dict[str, Any]]:
        return self._structured.get_timeline(range_key=range_key, limit=limit, local_tz=self._tz)

    def summarize(self, *, range_key: str, limit: int = 10) -> str:
        items = self.get_activity(range_key=range_key, limit=limit)
        if not items:
            return "No recent activity found."
        lines = []
        for item in items:
            lines.append(f'- [{item["timestamp_local"]}] {item["summary"]}')
        return "\n".join(lines)

