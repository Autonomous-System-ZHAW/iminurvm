"""Agent configuration (``agent.yaml``)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path("/etc/gpuboard/agent.yaml")


@dataclass(frozen=True)
class AgentConfig:
    """Settings read from ``agent.yaml``."""

    claim_path: Path = Path("/var/lib/gpuboard/claim.json")
    auto_claim_hours: float = 4.0
    idle_grace_minutes: float = 30.0
    pam_auto_claim_enabled: bool = True
    default_claim_hours: float = 4.0
    excluded_session_users: tuple[str, ...] = ()


def load_agent_config(path: Path | None = None) -> AgentConfig:
    """Load YAML settings; only an absent default config uses defaults."""
    config_path = path if path is not None else DEFAULT_CONFIG_PATH
    try:
        text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if path is not None:
            raise
        return AgentConfig()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid agent config {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"agent config {config_path} must be a mapping")
    allowed = {
        "claim_path",
        "auto_claim_hours",
        "idle_grace_minutes",
        "pam_auto_claim_enabled",
        "default_claim_hours",
        "excluded_session_users",
    }
    if any(not isinstance(key, str) or key not in allowed for key in data):
        raise ValueError(f"unknown agent config key in {config_path}")
    defaults = AgentConfig()
    claim_path = data.get("claim_path", str(defaults.claim_path))
    if not isinstance(claim_path, str) or not claim_path.strip():
        raise ValueError("claim_path must be a nonempty absolute path")
    claim = Path(claim_path)
    if not claim.is_absolute():
        raise ValueError("claim_path must be an absolute path")
    durations: dict[str, float] = {}
    for key in ("auto_claim_hours", "idle_grace_minutes", "default_claim_hours"):
        value = data.get(key, getattr(defaults, key))
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            or (key != "idle_grace_minutes" and value == 0)
        ):
            sign = "nonnegative" if key == "idle_grace_minutes" else "positive"
            raise ValueError(f"{key} must be a finite {sign} number")
        durations[key] = float(value)
    enabled = data.get("pam_auto_claim_enabled", defaults.pam_auto_claim_enabled)
    if not isinstance(enabled, bool):
        raise ValueError("pam_auto_claim_enabled must be a boolean")
    excluded = data.get("excluded_session_users", [])
    if not isinstance(excluded, list) or any(
        not isinstance(user, str)
        or not user
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in user)
        for user in excluded
    ):
        raise ValueError("excluded_session_users must be a list of nonempty usernames")
    if len(set(excluded)) != len(excluded):
        raise ValueError("excluded_session_users contains duplicate usernames")
    return AgentConfig(
        claim_path=claim,
        auto_claim_hours=durations["auto_claim_hours"],
        idle_grace_minutes=durations["idle_grace_minutes"],
        default_claim_hours=durations["default_claim_hours"],
        pam_auto_claim_enabled=enabled,
        excluded_session_users=tuple(excluded),
    )
