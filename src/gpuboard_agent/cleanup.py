"""Idle cleanup of expired claims."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from gpuboard_agent.cli._common import add_config_argument, claim_lock
from gpuboard_agent.config import AgentConfig, load_agent_config
from gpuboard_agent.gpu import parse_compute_apps_csv, query_compute_apps
from gpuboard_agent.sessions import find_vscode_users, list_login_sessions
from gpuboard_common.claimfile import delete_claim, is_cleanup_due, load_claim
from gpuboard_common.timeutil import now as current_time


def cleanup_expired_claim(config: AgentConfig, now: datetime) -> bool:
    """Delete the claim if expired past the grace period and the VM is idle.

    Any observed login, VS Code process, or GPU compute process prevents
    deletion. Collection failures propagate and leave the claim in place.
    Cooperating claim writers are locked through observation and deletion.
    """
    with claim_lock(config.claim_path):
        claim = load_claim(config.claim_path)
        if claim is None or not is_cleanup_due(
            claim, now, timedelta(minutes=config.idle_grace_minutes)
        ):
            return False
        if list_login_sessions() or find_vscode_users():
            return False
        if parse_compute_apps_csv(query_compute_apps()):
            return False
        delete_claim(config.claim_path)
        return True


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``vm-cleanup`` (run from a systemd timer)."""
    parser = argparse.ArgumentParser(prog="vm-cleanup", description=__doc__)
    add_config_argument(parser)
    args = parser.parse_args(argv)
    try:
        config = load_agent_config(Path(args.config) if args.config else None)
        removed = cleanup_expired_claim(config, current_time())
    except (
        OSError,
        ValueError,
        KeyError,
        OverflowError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"vm-cleanup: {exc}", file=sys.stderr)
        return 1
    print("Expired claim removed" if removed else "No claim removed")
    return 0
