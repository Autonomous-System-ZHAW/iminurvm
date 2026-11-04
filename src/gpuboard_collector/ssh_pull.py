"""Pull agent snapshots from the VMs over SSH."""

from __future__ import annotations

from gpuboard_collector.config import CollectorConfig
from gpuboard_common.models import VmInventory, VmSnapshot


def build_ssh_command(config: CollectorConfig, address: str) -> list[str]:
    """Return the ``ssh`` argv that runs the agent on ``address``."""
    raise NotImplementedError  # TODO(phase 3)


def pull_snapshot(config: CollectorConfig, vm: VmInventory) -> VmSnapshot:
    """Run the agent on one VM; raise on timeout or invalid JSON."""
    raise NotImplementedError  # TODO(phase 3)


def pull_all(
    config: CollectorConfig, vms: list[VmInventory]
) -> dict[int, VmSnapshot | Exception]:
    """Pull all running VMs concurrently; map vmid to snapshot or error."""
    raise NotImplementedError  # TODO(phase 3)
