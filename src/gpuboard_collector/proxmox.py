"""Read GPU-tagged VM inventory from the Proxmox API."""

from __future__ import annotations

import re
from dataclasses import replace

from proxmoxer import ProxmoxAPI

from gpuboard_collector.config import CollectorConfig, PveNodeConfig
from gpuboard_common.models import VmInventory

_HOSTPCI = re.compile(r"hostpci([0-9]+)")
_API_TIMEOUT_SECONDS = 10


def fetch_node_inventory(node: PveNodeConfig) -> list[VmInventory]:
    """Fetch tagged QEMU VMs from one node, including passthrough settings.

    All VM configurations are inspected for the exact ``gpu`` tag. API and
    parsing failures propagate rather than presenting an incomplete inventory.
    """
    user, separator, token_name = node.token_id.partition("!")
    if not separator or not user or not token_name or "!" in token_name:
        raise ValueError(f"invalid Proxmox token ID for node {node.name}")
    token = node.token_secret_file.read_text(encoding="utf-8").strip()
    if not token or any(char.isspace() for char in token):
        raise ValueError(f"invalid token secret file for node {node.name}")
    api = ProxmoxAPI(
        node.host,
        user=user,
        token_name=token_name,
        token_value=token,
        verify_ssl=node.verify_ssl,
        timeout=_API_TIMEOUT_SECONDS,
    )
    qemu = api.nodes(node.name).qemu
    rows = qemu.get()
    if not isinstance(rows, list):
        raise ValueError(f"invalid VM listing for node {node.name}")
    inventory: list[VmInventory] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"invalid VM listing entry for node {node.name}")
        vmid = row.get("vmid")
        if isinstance(vmid, bool) or not isinstance(vmid, int) or vmid <= 0:
            raise ValueError(f"invalid VM ID in listing for node {node.name}")
        if vmid in seen:
            raise ValueError(f"duplicate VM ID {vmid} on node {node.name}")
        seen.add(vmid)
        details = qemu(vmid).config.get()
        if not isinstance(details, dict):
            raise ValueError(f"invalid configuration for VM {vmid} on {node.name}")
        tags = details.get("tags", "")
        if not isinstance(tags, str):
            raise ValueError(f"invalid tags for VM {vmid} on {node.name}")
        if "gpu" not in tags.split(";"):
            continue
        name = row.get("name")
        if name is None or name == "":
            name = f"VM {vmid}"
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"invalid name for VM {vmid} on {node.name}")
        status = row.get("status")
        if status not in ("running", "stopped"):
            raise ValueError(f"invalid status for VM {vmid} on {node.name}: {status!r}")
        devices: list[tuple[int, str]] = []
        for key, value in details.items():
            if not isinstance(key, str):
                raise ValueError(f"invalid configuration key for VM {vmid}")
            match = _HOSTPCI.fullmatch(key)
            if match:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"invalid {key} for VM {vmid} on {node.name}")
                devices.append((int(match.group(1)), value))
        inventory.append(
            VmInventory(
                vmid=vmid,
                name=name,
                node=node.name,
                running=status == "running",
                hostpci=tuple(value for _, value in sorted(devices)),
            )
        )
    return inventory


def fetch_inventory(config: CollectorConfig) -> list[VmInventory]:
    """Combine node inventories and apply explicit VM address mappings."""
    inventory: list[VmInventory] = []
    seen: set[int] = set()
    for node in config.nodes:
        for vm in fetch_node_inventory(node):
            if vm.vmid in seen:
                raise ValueError(f"duplicate VM ID {vm.vmid} across nodes")
            seen.add(vm.vmid)
            inventory.append(replace(vm, address=config.vm_addresses.get(vm.vmid)))
    return sorted(inventory, key=lambda vm: (vm.node, vm.vmid))
