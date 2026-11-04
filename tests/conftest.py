"""Shared test helpers and fixture loaders."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from gpuboard_common.models import Claim, GpuProcess, Session, VmSnapshot
from gpuboard_common.timeutil import parse_iso

FIXTURES = Path(__file__).parent / "fixtures"
NOW = parse_iso("2026-11-04T10:00:00+01:00")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def now() -> datetime:
    return NOW


def make_claim(
    owner: str = "alice",
    start: timedelta = timedelta(hours=-1),
    end: timedelta = timedelta(hours=3),
    kind: str = "manual",
) -> Claim:
    """Claim relative to NOW."""
    return Claim(
        owner=owner,
        project="proj",
        message="",
        start=NOW + start,
        end=NOW + end,
        kind=kind,  # type: ignore[arg-type]
        pid=1 if kind == "run" else None,
        created_by=owner,
        created_at=NOW + start,
    )


def make_snapshot(
    claim: Claim | None = None,
    sessions: tuple[Session, ...] = (),
    gpu_processes: tuple[GpuProcess, ...] = (),
    **kwargs: object,
) -> VmSnapshot:
    """Snapshot with sensible defaults."""
    return VmSnapshot(
        hostname="gpu-101",
        collected_at=NOW,
        claim=claim,
        sessions=sessions,
        gpu_processes=gpu_processes,
        **kwargs,  # type: ignore[arg-type]
    )
