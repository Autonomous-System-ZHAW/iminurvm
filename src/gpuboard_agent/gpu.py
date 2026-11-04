"""GPU model and compute process detection."""

from __future__ import annotations

from gpuboard_common.models import GpuProcess


def read_gpu_model() -> str | None:
    """Return the GPU model name from ``nvidia-smi``, or ``None``."""
    raise NotImplementedError  # TODO(phase 1)


def query_compute_apps() -> str:
    """Run ``nvidia-smi --query-compute-apps`` and return the CSV text."""
    raise NotImplementedError  # TODO(phase 1)


def parse_compute_apps_csv(text: str) -> list[GpuProcess]:
    """Parse the CSV into processes with ``user`` still empty (pure)."""
    raise NotImplementedError  # TODO(phase 1)


def resolve_process_user(pid: int) -> str:
    """Map a PID to its Linux user via ``ps``."""
    raise NotImplementedError  # TODO(phase 1)


def list_gpu_processes() -> list[GpuProcess]:
    """Return GPU processes with user and container information filled in."""
    raise NotImplementedError  # TODO(phase 1)
