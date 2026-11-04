"""Idle cleanup of expired claims."""

from __future__ import annotations

from datetime import datetime

from gpuboard_agent.config import AgentConfig


def cleanup_expired_claim(config: AgentConfig, now: datetime) -> bool:
    """Delete the claim if expired past the grace period and the VM is idle.

    Return ``True`` if a claim was removed.
    """
    raise NotImplementedError  # TODO(phase 2)


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``vm-cleanup`` (run from a systemd timer)."""
    raise NotImplementedError  # TODO(phase 2)
