"""Pull agent snapshots from the VMs over SSH."""

from __future__ import annotations

import json
import logging
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from gpuboard_collector.config import CollectorConfig
from gpuboard_common.models import VmInventory, VmSnapshot
from gpuboard_common.serialize import snapshot_from_dict

logger = logging.getLogger(__name__)
MAX_WORKERS = 8


def build_ssh_command(config: CollectorConfig, address: str) -> list[str]:
    """Return the ``ssh`` argv that runs the agent on ``address``."""
    if not address or address.startswith("-") or any(c.isspace() for c in address):
        raise ValueError(f"invalid SSH address: {address!r}")
    if (
        not config.ssh_user
        or config.ssh_user.startswith("-")
        or any(c.isspace() for c in config.ssh_user)
    ):
        raise ValueError("invalid SSH user")
    if not config.agent_command or "\x00" in config.agent_command:
        raise ValueError("invalid agent command")
    return [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-i",
        str(config.ssh_key),
        "-l",
        config.ssh_user,
        "--",
        address,
        shlex.quote(config.agent_command),
    ]


def pull_snapshot(config: CollectorConfig, vm: VmInventory) -> VmSnapshot:
    """Run the agent on one VM; raise on timeout or invalid JSON."""
    if not vm.running:
        raise ValueError(f"VM {vm.vmid} is stopped")
    if vm.address is None:
        raise ValueError(f"VM {vm.vmid} has no configured SSH address")
    result = subprocess.run(
        build_ssh_command(config, vm.address),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=config.ssh_timeout_seconds,
    )
    if result.returncode:
        detail = result.stderr.strip() or "no error output"
        raise RuntimeError(
            f"VM {vm.vmid} SSH/agent failed ({result.returncode}): {detail}"
        )
    if result.stderr.strip():
        logger.warning("VM %s agent stderr: %s", vm.vmid, result.stderr.strip())
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"VM {vm.vmid} returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"VM {vm.vmid} snapshot must be a JSON object")
    return snapshot_from_dict(data)


def pull_all(
    config: CollectorConfig, vms: list[VmInventory]
) -> dict[int, VmSnapshot | Exception]:
    """Pull all running VMs concurrently; map vmid to snapshot or error."""
    running = [vm for vm in vms if vm.running]
    ids = [vm.vmid for vm in vms]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate VM ID in inventory")
    if not running:
        return {}
    results: dict[int, VmSnapshot | Exception] = {}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(running))) as executor:
        futures = {
            executor.submit(pull_snapshot, config, vm): vm.vmid for vm in running
        }
        for future in as_completed(futures):
            try:
                results[futures[future]] = future.result()
            except (
                OSError,
                ValueError,
                RuntimeError,
                subprocess.SubprocessError,
            ) as exc:
                results[futures[future]] = exc
    return results
