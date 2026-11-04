"""Merge inventory, agent snapshots and claims into the board state."""

from __future__ import annotations

from datetime import datetime

from gpuboard_common.models import BoardState, VmEntry, VmInventory, VmSnapshot


def build_entry(
    vm: VmInventory, result: VmSnapshot | Exception | None, now: datetime
) -> VmEntry:
    """Build one board row; stopped VMs are OFF, failed pulls UNREACHABLE."""
    raise NotImplementedError  # TODO(phase 3)


def merge(
    inventory: list[VmInventory],
    results: dict[int, VmSnapshot | Exception],
    now: datetime,
) -> BoardState:
    """Build the full board state, sorted by node and VM id."""
    raise NotImplementedError  # TODO(phase 3)


def write_status(board: BoardState, path: str) -> None:
    """Atomically write ``status.json``."""
    raise NotImplementedError  # TODO(phase 3)
