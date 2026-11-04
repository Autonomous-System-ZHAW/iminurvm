"""``gpu-board-collector`` entry point."""

from __future__ import annotations

from gpuboard_common.models import BoardState


def poll_once(config_path: str | None = None) -> BoardState:
    """One cycle: inventory -> pull -> merge -> write ``status.json``."""
    raise NotImplementedError  # TODO(phase 3)


def main(argv: list[str] | None = None) -> int:
    """Run the poll loop and the web server."""
    raise NotImplementedError  # TODO(phase 3)
