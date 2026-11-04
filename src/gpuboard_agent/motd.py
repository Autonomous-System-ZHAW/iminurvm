"""Login banner renderer (also used by the profile.d shim for VS Code)."""

from __future__ import annotations

from datetime import datetime

from gpuboard_common.models import VmSnapshot


def render_motd(snapshot: VmSnapshot, login_user: str, now: datetime) -> str:
    """Render claim, users, GPU usage and a warning for non-owners."""
    raise NotImplementedError  # TODO(phase 1)


def handover_warning(snapshot: VmSnapshot, now: datetime) -> str | None:
    """Warning for an upcoming planned claim (future reservations)."""
    raise NotImplementedError  # TODO(phase 5)


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``vm-motd``."""
    raise NotImplementedError  # TODO(phase 1)
