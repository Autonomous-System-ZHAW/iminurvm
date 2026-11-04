"""Docker containers and cgroup -> container mapping."""

from __future__ import annotations

from gpuboard_common.models import Container


def list_containers() -> list[Container]:
    """Return running containers from ``docker ps --format json``."""
    raise NotImplementedError  # TODO(phase 1)


def parse_docker_ps_json(text: str) -> list[Container]:
    """Parse line-delimited ``docker ps --format json`` output (pure)."""
    raise NotImplementedError  # TODO(phase 1)


def parse_labels(raw: str) -> dict[str, str]:
    """Parse docker's ``k=v,k2=v2`` label string into a dict."""
    raise NotImplementedError  # TODO(phase 1)


def container_id_from_cgroup(cgroup_text: str) -> str | None:
    """Extract a container ID from the content of ``/proc/<pid>/cgroup``."""
    raise NotImplementedError  # TODO(phase 1)


def find_container(container_id: str, containers: list[Container]) -> Container | None:
    """Match a (possibly shortened) container ID against known containers."""
    raise NotImplementedError  # TODO(phase 1)
