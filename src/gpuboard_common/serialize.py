"""JSON (de)serialization of snapshots and board state."""

from __future__ import annotations

from typing import Any

from gpuboard_common.models import BoardState, VmSnapshot


def snapshot_to_dict(snapshot: VmSnapshot) -> dict[str, Any]:
    """Convert a snapshot to a JSON-compatible dict (agent output)."""
    raise NotImplementedError  # TODO(phase 1)


def snapshot_from_dict(data: dict[str, Any]) -> VmSnapshot:
    """Parse the agent's JSON output into a snapshot (collector input)."""
    raise NotImplementedError  # TODO(phase 3)


def board_to_dict(board: BoardState) -> dict[str, Any]:
    """Convert the board state to the ``status.json`` structure."""
    raise NotImplementedError  # TODO(phase 3)
