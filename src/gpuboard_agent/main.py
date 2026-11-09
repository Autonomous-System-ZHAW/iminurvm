"""``vm-agent``: print a JSON snapshot of this VM to stdout."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from pathlib import Path

from gpuboard_agent.config import load_agent_config
from gpuboard_agent.docker import list_containers
from gpuboard_agent.gpu import list_gpu_processes, read_gpu_model
from gpuboard_agent.sessions import (
    find_vscode_users,
    list_login_sessions,
    merge_vscode_sessions,
)
from gpuboard_common.claimfile import load_claim
from gpuboard_common.models import VmSnapshot
from gpuboard_common.serialize import snapshot_to_dict
from gpuboard_common.timeutil import now


def build_snapshot(config_path: Path | None = None) -> VmSnapshot:
    """Collect local observations; fail if a required source is unavailable."""
    config = load_agent_config(config_path)
    sessions = merge_vscode_sessions(list_login_sessions(), find_vscode_users())
    containers = list_containers()
    gpu_model = read_gpu_model()
    processes = list_gpu_processes(containers)
    claim = load_claim(config.claim_path)
    return VmSnapshot(
        hostname=socket.gethostname(),
        collected_at=now(),
        gpu_model=gpu_model,
        sessions=tuple(sessions),
        containers=tuple(containers),
        gpu_processes=tuple(processes),
        claim=claim,
    )


def main(argv: list[str] | None = None) -> int:
    """Print a snapshot to stdout, or report collection failure on stderr."""
    parser = argparse.ArgumentParser(prog="vm-agent", description=__doc__)
    parser.add_argument("--config", type=Path, help="path to agent.yaml")
    args = parser.parse_args(argv)
    try:
        output = json.dumps(snapshot_to_dict(build_snapshot(args.config)))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"vm-agent: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0
