"""Display this VM's latest collector observation at login."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gpuboard_agent.cli._common import add_config_argument, current_user
from gpuboard_agent.cli.status import StatusBoard, StatusRow, _safe, fetch_status
from gpuboard_agent.config import load_agent_config
from gpuboard_common.claimfile import is_expired, is_planned
from gpuboard_common.timeutil import parse_iso


def render_motd(board: StatusBoard, row: StatusRow, login_user: str) -> str:
    """Render a VM observation, clearly labeled with freshness and warnings."""
    lines = [
        f"gpu-board | VM {row.vmid} ({_safe(row.name)}) | status: {row.status.value}",
        f"Board: {board.freshness} | snapshot: {row.freshness}",
        f"Board generated: {_safe(board.generated_at)}",
    ]
    if board.freshness != "FRESH" or row.freshness != "FRESH":
        lines.append("WARNING: collector information may be stale or unavailable.")
    snapshot = row.snapshot
    if snapshot is None:
        lines.append("VM observation unavailable; do not assume the VM is free.")
        if row.error:
            lines.append(f"Collector error: {_safe(row.error)}")
        return "\n".join(lines)
    lines.append(f"VM observed: {snapshot.collected_at.isoformat(timespec='seconds')}")
    claim = snapshot.claim
    if claim is None:
        lines.append("Claim: none observed")
    else:
        observed_at = parse_iso(board.assessed_at)
        claim_state = (
            "planned"
            if is_planned(claim, observed_at)
            else "expired" if is_expired(claim, observed_at) else "active"
        )
        lines.append(
            f"Claim ({claim_state} at assessment): {_safe(claim.owner)}"
            f" | project: {_safe(claim.project or '-')}"
            f" | until: {claim.end.isoformat(timespec='seconds')}"
        )
        if claim.message:
            lines.append(f"Message: {_safe(claim.message)}")
        if claim.owner != login_user:
            lines.append(
                f"WARNING: observed claim belongs to {_safe(claim.owner)}; "
                "ask before using or stopping their work."
            )
    users = ", ".join(sorted({_safe(session.user) for session in snapshot.sessions}))
    gpu_users = ", ".join(
        sorted({_safe(process.effective_owner) for process in snapshot.gpu_processes})
    )
    lines.append(f"Sessions: {users or '-'} | GPU users: {gpu_users or '-'}")
    lines.append(f"GPU: {_safe(snapshot.gpu_model or '-')}")
    lines.append(
        "Observations can lag behind local changes. Use vm-status for all VMs."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Fetch and render the configured VM's collector observation."""
    parser = argparse.ArgumentParser(prog="vm-motd", description=__doc__)
    add_config_argument(parser)
    args = parser.parse_args(argv)
    try:
        config = load_agent_config(Path(args.config) if args.config else None)
        if config.vmid is None:
            raise ValueError("set vmid in agent.yaml")
        if config.collector_status_url is None:
            raise ValueError("set collector_status_url in agent.yaml")
        board, _ = fetch_status(config.collector_status_url)
        row = next((row for row in board.rows if row.vmid == config.vmid), None)
        if row is None:
            raise ValueError(f"VM {config.vmid} not found in collector inventory")
        print(render_motd(board, row, current_user()))
    except (OSError, ValueError, OverflowError, KeyError) as exc:
        print(f"gpu-board: status unavailable: {_safe(str(exc))}", file=sys.stderr)
        return 1
    return 0
