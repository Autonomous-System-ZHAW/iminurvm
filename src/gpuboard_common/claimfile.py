"""Load, save and validate ``claim.json`` plus expiry helpers."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast, get_args

from gpuboard_common.models import Claim, ClaimKind
from gpuboard_common.timeutil import format_iso, parse_iso

CLAIM_KINDS: tuple[str, ...] = get_args(ClaimKind)
_REQUIRED = ("owner", "project", "start", "end", "kind", "created_by", "created_at")


class ClaimError(ValueError):
    """Raised when a claim file or dict is malformed."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp without UTC offset")
    return value.astimezone(UTC)


def claim_from_dict(data: Mapping[str, Any]) -> Claim:
    """Build a validated ``Claim`` from a decoded JSON object."""
    missing = [key for key in _REQUIRED if key not in data]
    if missing:
        raise ClaimError(f"missing fields: {', '.join(missing)}")
    try:
        claim = Claim(
            owner=str(data["owner"]),
            project=str(data["project"]),
            message=str(data.get("message") or ""),
            start=parse_iso(str(data["start"])),
            end=parse_iso(str(data["end"])),
            kind=cast(ClaimKind, data["kind"]),
            pid=None if data.get("pid") is None else int(data["pid"]),
            created_by=str(data["created_by"]),
            created_at=parse_iso(str(data["created_at"])),
        )
    except (TypeError, ValueError) as exc:
        raise ClaimError(str(exc)) from exc
    validate_claim(claim)
    return claim


def claim_to_dict(claim: Claim) -> dict[str, Any]:
    """Serialize a claim to the on-disk JSON structure."""
    return {
        "owner": claim.owner,
        "project": claim.project,
        "message": claim.message,
        "start": format_iso(claim.start),
        "end": format_iso(claim.end),
        "kind": claim.kind,
        "pid": claim.pid,
        "created_by": claim.created_by,
        "created_at": format_iso(claim.created_at),
    }


def validate_claim(claim: Claim) -> None:
    """Raise ``ClaimError`` if the claim violates the file format rules."""
    if not claim.owner.strip():
        raise ClaimError("owner must not be empty")
    if claim.kind not in CLAIM_KINDS:
        raise ClaimError(f"invalid kind: {claim.kind!r}")
    if _utc(claim.end) <= _utc(claim.start):
        raise ClaimError("end must be after start")
    if claim.kind == "run" and claim.pid is None:
        raise ClaimError("kind 'run' requires a pid")


def load_claim(path: Path) -> Claim | None:
    """Read a claim file. Return ``None`` if it does not exist."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClaimError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ClaimError(f"{path} must contain a JSON object")
    return claim_from_dict(data)


def save_claim(path: Path, claim: Claim) -> None:
    """Atomically write a claim file (group-readable/writable, mode 0664)."""
    validate_claim(claim)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".claim-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(claim_to_dict(claim), handle, indent=2)
            handle.write("\n")
        os.chmod(tmp_name, 0o664)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def delete_claim(path: Path) -> None:
    """Remove the claim file; a missing file is not an error."""
    path.unlink(missing_ok=True)


def is_planned(claim: Claim, now: datetime) -> bool:
    """True if the claim starts in the future (future reservations)."""
    return _utc(now) < _utc(claim.start)


def is_expired(claim: Claim, now: datetime) -> bool:
    """True once ``end`` has been reached."""
    return _utc(now) >= _utc(claim.end)


def is_active(claim: Claim, now: datetime) -> bool:
    """True while ``start <= now < end``."""
    return not is_planned(claim, now) and not is_expired(claim, now)


def remaining(claim: Claim, now: datetime) -> timedelta:
    """Time left until ``end``; negative once expired."""
    return _utc(claim.end) - _utc(now)


def is_cleanup_due(claim: Claim, now: datetime, grace: timedelta) -> bool:
    """True if the claim expired longer than ``grace`` ago.

    The caller must additionally check that the VM is idle (no sessions or
    GPU processes) before deleting the claim.
    """
    return _utc(now) >= _utc(claim.end) + grace
