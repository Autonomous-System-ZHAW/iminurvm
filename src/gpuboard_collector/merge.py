"""Merge inventory, agent snapshots and claims into the board state."""

from __future__ import annotations

from datetime import datetime

from gpuboard_common.models import BoardState, VmEntry, VmInventory, VmSnapshot
from gpuboard_common.status import derive_status


def build_entry(
    vm: VmInventory, result: VmSnapshot | Exception | None, now: datetime
) -> VmEntry:
    """Build a row and derive status from inventory and the current pull result.

    A stopped VM or failed pull has no current snapshot; preserve pull errors
    in the entry rather than treating missing data as an idle VM.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("merge time must include a UTC offset")
    if not vm.running:
        return VmEntry(vm, derive_status(vm, None, now))
    if isinstance(result, Exception):
        error = str(result) or type(result).__name__
        return VmEntry(vm, derive_status(vm, None, now), error=error)
    if result is None:
        return VmEntry(
            vm, derive_status(vm, None, now), error="No snapshot result received"
        )
    return VmEntry(vm, derive_status(vm, result, now), snapshot=result)


def merge(
    inventory: list[VmInventory],
    results: dict[int, VmSnapshot | Exception],
    now: datetime,
) -> BoardState:
    """Build the full board state, sorted by node and VM id."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("merge time must include a UTC offset")
    ids = [vm.vmid for vm in inventory]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate VM ID in inventory")
    unknown = results.keys() - set(ids)
    if unknown:
        raise ValueError(f"snapshot results for unknown VM IDs: {sorted(unknown)}")
    entries = tuple(
        build_entry(vm, results.get(vm.vmid), now)
        for vm in sorted(inventory, key=lambda item: (item.node, item.vmid))
    )
    return BoardState(generated_at=now, vms=entries)


def write_status(board: BoardState, path: str) -> None:
    """Atomically write ``status.json``."""
    raise NotImplementedError  # TODO(phase 3)
