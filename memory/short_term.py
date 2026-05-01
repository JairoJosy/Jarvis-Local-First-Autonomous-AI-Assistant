from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any


class ShortTermMemory:
    def __init__(self, max_turns: int = 20) -> None:
        self._max_turns = max_turns
        self._history: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=self._max_turns)
        )
        self._state: dict[str, dict[str, Any]] = defaultdict(dict)
        self._lock = Lock()

    def add_turn(self, session_id: str, role: str, text: str) -> None:
        with self._lock:
            self._history[session_id].append(
                {
                    "role": role,
                    "text": text,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
            )

    def recent(self, session_id: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            turns = list(self._history.get(session_id, deque()))
        return turns[-limit:]

    def set_state(self, session_id: str, key: str, value: Any) -> None:
        with self._lock:
            self._state[session_id][key] = value

    def get_state(self, session_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._state.get(session_id, {}).get(key, default)

