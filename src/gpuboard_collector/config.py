"""Collector configuration (``collector.yaml``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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
    """Load the config file (requires PyYAML)."""
    raise NotImplementedError  # TODO(phase 3)
