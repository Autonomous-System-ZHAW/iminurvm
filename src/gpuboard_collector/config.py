"""Collector configuration (``collector.yaml``)."""

from __future__ import annotations

import math
from collections.abc import Hashable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path("/etc/gpuboard/collector.yaml")


@dataclass(frozen=True)
class PveNodeConfig:
    """One Proxmox node reachable through the API."""

    name: str
    host: str
    token_id: str
    token_secret_file: Path
    verify_ssl: bool = True


@dataclass(frozen=True)
class CollectorConfig:
    """Settings read from ``collector.yaml``."""

    nodes: tuple[PveNodeConfig, ...] = ()
    ssh_user: str = "gpuboard"
    ssh_key: Path = Path("/etc/gpuboard/id_ed25519")
    ssh_timeout_seconds: float = 10.0
    agent_command: str = "vm-agent"
    poll_interval_seconds: float = 30.0
    status_path: Path = Path("/var/lib/gpuboard/status.json")
    listen_host: str = "0.0.0.0"
    listen_port: int = 8080
    vm_addresses: dict[int, str] = field(default_factory=dict)


def load_collector_config(path: Path | None = None) -> CollectorConfig:
    """Load and validate collector YAML without accessing credentials or hosts."""
    config_path = path if path is not None else DEFAULT_CONFIG_PATH
    text = config_path.read_text(encoding="utf-8")
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid collector config {config_path}: {exc}") from exc
    root = _mapping(
        data,
        {
            "proxmox",
            "ssh_user",
            "ssh_key",
            "ssh_timeout_seconds",
            "agent_command",
            "poll_interval_seconds",
            "status_path",
            "listen_host",
            "listen_port",
            "vm_addresses",
        },
        "collector config",
    )
    proxmox = _mapping(root.get("proxmox"), {"nodes"}, "proxmox")
    raw_nodes = proxmox.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("proxmox.nodes must be a nonempty list")
    nodes: list[PveNodeConfig] = []
    names: set[str] = set()
    for index, item in enumerate(raw_nodes):
        context = f"proxmox.nodes[{index}]"
        node = _mapping(
            item,
            {"name", "host", "token_id", "token_secret_file", "verify_ssl"},
            context,
        )
        name = _text(node.get("name"), f"{context}.name")
        if name in names:
            raise ValueError(f"duplicate Proxmox node name: {name}")
        names.add(name)
        verify_ssl = node.get("verify_ssl", True)
        if not isinstance(verify_ssl, bool):
            raise ValueError(f"{context}.verify_ssl must be a boolean")
        nodes.append(
            PveNodeConfig(
                name=name,
                host=_text(node.get("host"), f"{context}.host"),
                token_id=_text(node.get("token_id"), f"{context}.token_id"),
                token_secret_file=_path(
                    node.get("token_secret_file"), f"{context}.token_secret_file"
                ),
                verify_ssl=verify_ssl,
            )
        )

    raw_addresses = root.get("vm_addresses", {})
    if not isinstance(raw_addresses, dict):
        raise ValueError("vm_addresses must be a mapping")
    addresses: dict[int, str] = {}
    for raw_id, value in raw_addresses.items():
        if isinstance(raw_id, bool) or not (
            isinstance(raw_id, int)
            or (isinstance(raw_id, str) and raw_id.isascii() and raw_id.isdecimal())
        ):
            raise ValueError("vm_addresses keys must be positive VM IDs")
        vmid = int(raw_id)
        if vmid <= 0 or vmid in addresses:
            raise ValueError(f"invalid or duplicate VM ID: {raw_id!r}")
        addresses[vmid] = _text(value, f"vm_addresses[{vmid}]")

    defaults = CollectorConfig()
    port = root.get("listen_port", defaults.listen_port)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("listen_port must be an integer from 1 to 65535")
    return CollectorConfig(
        nodes=tuple(nodes),
        ssh_user=_text(root.get("ssh_user", defaults.ssh_user), "ssh_user"),
        ssh_key=_path(root.get("ssh_key", str(defaults.ssh_key)), "ssh_key"),
        ssh_timeout_seconds=_positive_number(
            root.get("ssh_timeout_seconds", defaults.ssh_timeout_seconds),
            "ssh_timeout_seconds",
        ),
        agent_command=_text(
            root.get("agent_command", defaults.agent_command), "agent_command"
        ),
        poll_interval_seconds=_positive_number(
            root.get("poll_interval_seconds", defaults.poll_interval_seconds),
            "poll_interval_seconds",
        ),
        status_path=_path(
            root.get("status_path", str(defaults.status_path)), "status_path"
        ),
        listen_host=_text(root.get("listen_host", defaults.listen_host), "listen_host"),
        listen_port=port,
        vm_addresses=addresses,
    )


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""

    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict[Hashable, object]:
        """Construct a mapping without silently overriding duplicate keys."""
        self.flatten_mapping(node)
        result: dict[Hashable, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, Hashable):
                raise ValueError("YAML mapping keys must be hashable")
            if key in result:
                raise ValueError(f"duplicate YAML key: {key!r}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _mapping(value: object, allowed: set[str], context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping")
    if any(not isinstance(key, str) or key not in allowed for key in value):
        raise ValueError(f"unknown key in {context}")
    return value


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(
            f"{context} must be a nonempty string without outer whitespace"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{context} must not contain control characters")
    return value


def _path(value: object, context: str) -> Path:
    path = Path(_text(value, context))
    if not path.is_absolute():
        raise ValueError(f"{context} must be an absolute path")
    return path


def _positive_number(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be a finite positive number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{context} must be a finite positive number") from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{context} must be a finite positive number")
    return result
