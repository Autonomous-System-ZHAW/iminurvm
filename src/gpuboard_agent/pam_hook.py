"""Optional ``pam_exec`` hook: soft auto-claim on login to a FREE VM."""

from __future__ import annotations

from datetime import datetime

from gpuboard_agent.config import AgentConfig


def should_auto_claim(config: AgentConfig, user: str, now: datetime) -> bool:
    """True if enabled, ``user`` is a real user and the VM has no live claim."""
    raise NotImplementedError  # TODO(phase 4)


def refresh_auto_claim(config: AgentConfig, user: str, now: datetime) -> bool:
    """Extend an ``auto`` claim of ``user`` while they are still active."""
    raise NotImplementedError  # TODO(phase 4)


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``vm-pam-hook``; must never fail a login (return 0)."""
    raise NotImplementedError  # TODO(phase 4)
