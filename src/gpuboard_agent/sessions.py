"""Logged-in session detection."""

from __future__ import annotations

from gpuboard_common.models import Session


def list_login_sessions() -> list[Session]:
    """Return sessions from ``loginctl list-sessions`` / ``who``."""
    raise NotImplementedError  # TODO(phase 1)


def parse_loginctl_output(text: str) -> list[Session]:
    """Parse ``loginctl`` output into sessions (pure, testable)."""
    raise NotImplementedError  # TODO(phase 1)


def find_vscode_users() -> set[str]:
    """Return users that own ``.vscode-server`` processes."""
    raise NotImplementedError  # TODO(phase 1)


def merge_vscode_sessions(
    sessions: list[Session], vscode_users: set[str]
) -> list[Session]:
    """Mark/add sessions for users connected through VS Code Remote."""
    raise NotImplementedError  # TODO(phase 1)
