"""Plain dataclasses describing a VM, its claim and the derived board state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

ClaimKind = Literal["manual", "auto", "run"]
SessionKind = Literal["ssh", "vscode", "local"]


class VmStatus(StrEnum):
    """The single status derived per VM."""

    FREE = "FREE"
    CLAIMED = "CLAIMED"
    CLAIM_EXPIRED = "CLAIM_EXPIRED"
    UNCLAIMED_USAGE = "UNCLAIMED_USAGE"
    CONFLICT = "CONFLICT"
    OFF_UNREACHABLE = "OFF_UNREACHABLE"


@dataclass(frozen=True)
class Claim:
    """A social reservation of a VM. Never enforced technically."""

    owner: str
    project: str
    message: str
    start: datetime
    end: datetime
    kind: ClaimKind
    created_by: str
    created_at: datetime
    pid: int | None = None


@dataclass(frozen=True)
class Session:
    """A logged-in user session (loginctl/who) or a VS Code Remote session."""

    user: str
    kind: SessionKind = "ssh"
    tty: str | None = None
    remote_host: str | None = None
    since: datetime | None = None


@dataclass(frozen=True)
class Container:
    """A running Docker container with the labels we care about."""

    id: str
    name: str
    image: str = ""
    status: str = ""
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def owner(self) -> str | None:
        """Value of the ``owner`` label, if any."""
        return self.labels.get("owner")

    @property
    def project(self) -> str | None:
        """Value of the ``project`` label, if any."""
        return self.labels.get("project")


@dataclass(frozen=True)
class GpuProcess:
    """A compute process on the GPU, mapped to a Linux user and container."""

    pid: int
    user: str
    name: str = ""
    gpu_memory_mib: int | None = None
    gpu_uuid: str | None = None
    container_id: int | None = None
    container: str | None = None
    container_owner: str | None = None
    container_project: str | None = None

    @property
    def effective_owner(self) -> str:
        """Container ``owner`` label if present, else the Linux user.

        Container processes usually run as root, so the label is more telling.
        """
        return self.container_owner or self.user


@dataclass(frozen=True)
class VmSnapshot:
    """Point-in-time observations reported by the VM agent."""

    hostname: str
    collected_at: datetime
    gpu_model: str | None = None
    sessions: tuple[Session, ...] = ()
    gpu_processes: tuple[GpuProcess, ...] = ()
    containers: tuple[Container, ...] = ()
    claim: Claim | None = None


@dataclass(frozen=True)
class VmInventory:
    """Collector-owned VM inventory, including Proxmox's running state."""

    vmid: int
    name: str
    node: str
    running: bool
    hostpci: tuple[str, ...] = ()
    address: str | None = None


@dataclass(frozen=True)
class VmEntry:
    """Collector-owned board row, with a snapshot only if the pull succeeded."""

    inventory: VmInventory
    status: VmStatus
    snapshot: VmSnapshot | None = None
    error: str | None = None


@dataclass(frozen=True)
class BoardState:
    """The full derived state written to ``status.json``."""

    generated_at: datetime
    vms: tuple[VmEntry, ...] = ()
