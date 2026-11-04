"""Agent configuration (``agent.yaml``)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("/etc/gpuboard/agent.yaml")


@dataclass(frozen=True)
class AgentConfig:
    """Settings read from ``agent.yaml``."""

    claim_path: Path = Path("/var/lib/gpuboard/claim.json")
    auto_claim_hours: float = 4.0
    idle_grace_minutes: float = 30.0
    pam_auto_claim_enabled: bool = True
    default_claim_hours: float = 4.0


def load_agent_config(path: Path | None = None) -> AgentConfig:
    """Load the config file, falling back to defaults if it does not exist."""
    raise NotImplementedError  # TODO(phase 1): lazy `import yaml`, map keys
