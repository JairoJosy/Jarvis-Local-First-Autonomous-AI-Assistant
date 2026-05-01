from __future__ import annotations

from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


TZ_ALIASES = {
    "Asia/Calcutta": "Asia/Kolkata",
}


def resolve_tz_name(name: str) -> str:
    return TZ_ALIASES.get(name, name)


def safe_zoneinfo(name: str):
    candidates = [name, resolve_tz_name(name), "UTC"]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except ZoneInfoNotFoundError:
            continue
    return timezone.utc

