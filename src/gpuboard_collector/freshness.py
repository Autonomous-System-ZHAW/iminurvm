"""Assess observation freshness separately from VM ownership status."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from gpuboard_common.models import BoardState

FUTURE_TOLERANCE = timedelta(seconds=30)
STALE_INTERVALS = 3


class Freshness(StrEnum):
    """Freshness of an observation, independent of the derived VM status."""

    FRESH = "FRESH"
    STALE = "STALE"
    CLOCK_WARNING = "CLOCK_WARNING"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class BoardFreshness:
    """Freshness of the board and each VM's snapshot by VM ID."""

    board: Freshness
    snapshots: dict[int, Freshness]


def _validate_time(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("freshness timestamps must include a UTC offset")


def _validate_interval(value: float) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError("poll interval must be finite and positive")


def assess_timestamp(
    observed_at: datetime, now: datetime, poll_interval_seconds: float
) -> Freshness:
    """Assess timestamp age using three intervals and a 30-second future tolerance."""
    _validate_time(observed_at)
    _validate_time(now)
    _validate_interval(poll_interval_seconds)
    age = now.astimezone(UTC) - observed_at.astimezone(UTC)
    if age < -FUTURE_TOLERANCE:
        return Freshness.CLOCK_WARNING
    if age.total_seconds() > STALE_INTERVALS * poll_interval_seconds:
        return Freshness.STALE
    return Freshness.FRESH


def assess_board(
    board: BoardState | None, now: datetime, poll_interval_seconds: float
) -> BoardFreshness:
    """Assess board and VM timestamps at read time without modifying status."""
    _validate_time(now)
    _validate_interval(poll_interval_seconds)
    if board is None:
        return BoardFreshness(Freshness.UNAVAILABLE, {})
    ids = [entry.inventory.vmid for entry in board.vms]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate VM ID in board")
    snapshots: dict[int, Freshness] = {}
    for entry in board.vms:
        if not entry.inventory.running:
            freshness = Freshness.NOT_APPLICABLE
        elif entry.snapshot is None:
            freshness = Freshness.UNAVAILABLE
        else:
            freshness = assess_timestamp(
                entry.snapshot.collected_at, now, poll_interval_seconds
            )
        snapshots[entry.inventory.vmid] = freshness
    return BoardFreshness(
        board=assess_timestamp(board.generated_at, now, poll_interval_seconds),
        snapshots=snapshots,
    )
