"""Helpers shared by the CLI commands."""

from __future__ import annotations

import argparse
import fcntl
import math
import os
import pwd
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

EXIT_NOT_IMPLEMENTED = 70


def current_user() -> str:
    """Return the invoking Linux user name."""
    return pwd.getpwuid(os.getuid()).pw_name


def parse_duration(text: str) -> float:
    """Parse a positive duration such as ``90m``, ``4h`` or ``1d`` into hours."""
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([mhd])", text)
    if not match:
        raise ValueError("duration must be a positive number followed by m, h or d")
    value = float(match.group(1))
    hours = value * {"m": 1 / 60, "h": 1, "d": 24}[match.group(2)]
    return validate_duration(hours)


def validate_duration(hours: float) -> float:
    """Validate duration against the claim file's second precision."""
    if not math.isfinite(hours) or hours < 1 / 3600:
        raise ValueError("duration must be finite and at least one second")
    return hours


def add_duration(start: datetime, hours: float) -> datetime:
    """Add elapsed hours, including across daylight-saving transitions."""
    return (start.astimezone(UTC) + timedelta(hours=hours)).astimezone(start.tzinfo)


@contextmanager
def claim_lock(path: Path) -> Iterator[None]:
    """Serialize cooperating claim writers using a persistent lock file."""
    lock_path = path.with_name(f".{path.name}.lock")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDONLY, 0o664)
    except FileExistsError:
        fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_uid == os.geteuid():
            os.fchmod(fd, 0o664)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def add_config_argument(parser: argparse.ArgumentParser) -> None:
    """Add the common ``--config`` option."""
    parser.add_argument("--config", help="path to agent.yaml")


def not_implemented(command: str) -> int:
    """Placeholder body for stubbed commands."""
    print(f"{command}: not implemented yet", file=sys.stderr)
    return EXIT_NOT_IMPLEMENTED
