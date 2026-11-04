"""Proxmox API access (read-only token, ``PVEAuditor`` role)."""

from __future__ import annotations

from gpuboard_collector.config import CollectorConfig, PveNodeConfig
from gpuboard_common.models import VmInventory


def fetch_node_inventory(node: PveNodeConfig) -> list[VmInventory]:
    """List the VMs of one node incl. ``hostpci`` passthrough devices."""
    raise NotImplementedError  # TODO(phase 3)


def fetch_inventory(config: CollectorConfig) -> list[VmInventory]:
    """Combine the inventories of all configured nodes."""
    raise NotImplementedError  # TODO(phase 3)


def has_gpu_passthrough(vm: VmInventory) -> bool:
    """True if the VM has at least one ``hostpci`` device."""
    raise NotImplementedError  # TODO(phase 3)
