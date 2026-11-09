"""Login banner renderer (also used by the profile.d shim for VS Code)."""

from __future__ import annotations

from datetime import datetime

from gpuboard_common.models import VmEntry, VmSnapshot


def render_motd(entry: VmEntry, login_user: str, now: datetime) -> str:
    """Render collector-derived status, observed claim, users and warnings."""
    raise NotImplementedError  # TODO(phase 3)


def handover_warning(snapshot: VmSnapshot, now: datetime) -> str | None:
    """Warning for an upcoming planned claim (future reservations)."""
    raise NotImplementedError  # TODO(phase 5)


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``vm-motd``."""
    raise NotImplementedError  # TODO(phase 3)
