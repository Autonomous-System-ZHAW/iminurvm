"""``vm-agent``: print a JSON snapshot of this VM to stdout."""

from __future__ import annotations

from pathlib import Path

from gpuboard_common.models import VmSnapshot


def build_snapshot(config_path: Path | None = None) -> VmSnapshot:
    """Collect sessions, GPU processes, containers and the claim."""
    raise NotImplementedError  # TODO(phase 1)


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``vm-agent``."""
    raise NotImplementedError  # TODO(phase 1)
