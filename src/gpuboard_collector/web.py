"""Read-only dashboard and Prometheus ``/metrics``."""

from __future__ import annotations

from collections.abc import Callable

from gpuboard_common.models import BoardState


def render_dashboard(board: BoardState) -> str:
    """Render the auto-refreshing HTML page (Jinja2 template)."""
    raise NotImplementedError  # TODO(phase 3)


def render_metrics(board: BoardState) -> str:
    """Render basic gauges in Prometheus text format."""
    raise NotImplementedError  # TODO(phase 3)


def serve(host: str, port: int, get_board: Callable[[], BoardState]) -> None:
    """Serve ``/``, ``/status.json`` and ``/metrics`` via ``http.server``."""
    raise NotImplementedError  # TODO(phase 3)
