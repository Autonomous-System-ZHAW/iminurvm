"""Timestamp helpers. All stored timestamps are ISO 8601 with UTC offset."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("Europe/Zurich")


def now() -> datetime:
    """Return the current time as a timezone-aware datetime (Europe/Zurich)."""
    return datetime.now(DISPLAY_TZ)


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string; raise ``ValueError`` if it has no offset."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timestamp without UTC offset: {value!r}")
    return parsed


def format_iso(value: datetime) -> str:
    """Format an aware datetime as ISO 8601 with offset, second precision."""
    if value.tzinfo is None:
        raise ValueError("naive datetime")
    return value.isoformat(timespec="seconds")


def to_display(value: datetime) -> datetime:
    """Convert an aware datetime to Europe/Zurich for display."""
    return value.astimezone(DISPLAY_TZ)
