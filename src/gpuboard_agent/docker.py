"""Collect running Docker containers and map process cgroups to container IDs.

The inventory and cgroup helpers are independent: callers read a process's
``/proc/<pid>/cgroup``, extract its Docker ID, and match that ID against the
containers returned by :func:`list_containers`. The GPU collector that will
connect these steps is not implemented yet.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

from gpuboard_common.models import Container

# Accept both full Docker IDs and the commonly displayed 12-character prefix.
_CONTAINER_ID = re.compile(r"[0-9a-f]{12,64}")
_DOCKER_SCOPE = re.compile(r"docker-([0-9a-f]{12,64})\.scope")


def _ps_rows(text: str) -> list[dict[str, Any]]:
    """Validate line-delimited ``docker ps --format json`` inventory fields.

    Blank lines are ignored. Each nonblank line must be an object with
    nonempty string fields ``ID``, ``Names``, ``Image`` and ``Status``;
    invalid JSON or fields raise ``ValueError``. Labels are handled separately.
    """
    rows = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid docker ps JSON on line {line_number}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"docker ps line {line_number} is not an object")
        for key in ("ID", "Names", "Image", "Status"):
            if not isinstance(data.get(key), str) or not data[key]:
                raise ValueError(f"docker ps line {line_number}: invalid {key}")
        if not _CONTAINER_ID.fullmatch(data["ID"]):
            raise ValueError(f"docker ps line {line_number}: invalid ID")
        rows.append(data)
    return rows


def list_containers() -> list[Container]:
    """Return running Docker containers with exact labels from inspection.

    ``docker ps --no-trunc`` supplies full IDs and display information.
    ``docker inspect`` supplies the labels as a JSON object, avoiding the
    ambiguity of comma-separated display labels. Output order follows
    ``docker ps``. An empty inventory returns an empty list without inspection.

    Docker CLI failures (including missing executable, permission errors and
    command timeouts) propagate. Invalid output, duplicate IDs, missing inspect
    results or a container no longer running at inspection raise ``ValueError``.
    The two commands are not an atomic snapshot; callers should handle
    collection failures if containers change between them.
    """
    result = subprocess.run(
        ["docker", "ps", "--no-trunc", "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    rows = _ps_rows(result.stdout)
    if not rows:
        return []
    ids = [row["ID"] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("docker ps returned duplicate container IDs")
    # Inspect label maps rather than the lossy comma-separated display string.
    inspection = subprocess.run(
        ["docker", "inspect", "--type", "container", *ids],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    try:
        details = json.loads(inspection.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid docker inspect JSON") from exc
    if not isinstance(details, list):
        raise ValueError("docker inspect must return an array")
    # Inspect results can arrive in a different order than the ps rows.
    labels_by_id: dict[str, dict[str, str]] = {}
    for item in details:
        if not isinstance(item, dict):
            raise ValueError("docker inspect entry must be an object")
        container_id = item.get("Id")
        config = item.get("Config")
        state = item.get("State")
        if (
            not isinstance(container_id, str)
            or container_id not in ids
            or container_id in labels_by_id
            or not isinstance(config, dict)
            or "Labels" not in config
            or not isinstance(state, dict)
            or state.get("Running") is not True
        ):
            raise ValueError("invalid or no longer running inspected container")
        labels = config.get("Labels")
        if labels is None:
            labels = {}
        if not isinstance(labels, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in labels.items()
        ):
            raise ValueError(f"invalid labels for container {container_id}")
        labels_by_id[container_id] = labels
    if set(labels_by_id) != set(ids):
        raise ValueError("docker inspect did not return every listed container")
    return [
        Container(
            id=row["ID"],
            name=row["Names"],
            image=row["Image"],
            status=row["Status"],
            labels=labels_by_id[row["ID"]],
        )
        for row in rows
    ]


def parse_docker_ps_json(text: str) -> list[Container]:
    """Parse line-delimited ``docker ps --format json`` into containers.

    Each row must include a string ``Labels`` field alongside the inventory
    fields validated by ``_ps_rows``. Blank input returns an empty list;
    invalid rows or malformed display labels raise ``ValueError``.

    The comma-separated display format cannot reliably encode commas within
    label values, and some ambiguous strings can appear valid. Use
    ``list_containers`` when exact labels are needed.
    """
    containers = []
    for row in _ps_rows(text):
        labels = row.get("Labels")
        if not isinstance(labels, str):
            raise ValueError("docker ps Labels must be a string")
        containers.append(
            Container(
                id=row["ID"],
                name=row["Names"],
                image=row["Image"],
                status=row["Status"],
                labels=parse_labels(labels),
            )
        )
    return containers


def parse_labels(raw: str) -> dict[str, str]:
    """Parse comma-separated Docker display labels into a string mapping.

    An empty string yields an empty mapping. Values may be empty or contain
    ``=``. Missing separators, empty keys and duplicate keys raise
    ``ValueError``. Commas within values cannot be distinguished from label
    separators, so even successfully parsed output may be ambiguous.
    """
    if not raw:
        return {}
    labels: dict[str, str] = {}
    for entry in raw.split(","):
        key, separator, value = entry.partition("=")
        if not separator or not key or key in labels:
            raise ValueError(f"invalid or ambiguous Docker label: {entry!r}")
        labels[key] = value
    return labels


def container_id_from_cgroup(cgroup_text: str) -> str | None:
    """Extract a Docker container ID from ``/proc/<pid>/cgroup`` content.

    Recognized path components are ``/docker/<id>`` and
    ``docker-<id>.scope``, including nested child cgroups. IDs must be
    12-64 lowercase hexadecimal characters. Multiple controller lines may
    refer to the same ID; conflicting IDs or malformed lines raise
    ``ValueError``.

    Return ``None`` if no recognized Docker path is found. Other runtimes,
    ordinary user cgroups and unrecognized Docker layouts are not detected.
    """
    ids: set[str] = set()
    for line in cgroup_text.splitlines():
        if not line.strip():
            continue
        # A cgroup line is hierarchy ID, controllers, and path; the path
        # itself can contain colons.
        fields = line.split(":", 2)
        if len(fields) != 3 or not fields[0].isdigit() or not fields[2].startswith("/"):
            raise ValueError(f"invalid cgroup line: {line!r}")
        parts = fields[2].split("/")
        for index, part in enumerate(parts):
            match = _DOCKER_SCOPE.fullmatch(part)
            if match:
                ids.add(match.group(1))
            elif (
                index and parts[index - 1] == "docker" and _CONTAINER_ID.fullmatch(part)
            ):
                ids.add(part)
    if len(ids) > 1:
        raise ValueError("cgroup contains multiple Docker container IDs")
    return next(iter(ids), None)


def find_container(container_id: str, containers: list[Container]) -> Container | None:
    """Match a full ID or prefix against a list of observed containers.

    Either the supplied ID or the stored container ID may be the shorter
    prefix. Return the single match, or ``None`` when there is no match.
    Invalid input IDs and multiple matches raise ``ValueError``; callers must
    not assume an ambiguous prefix identifies a particular container.
    """
    if not _CONTAINER_ID.fullmatch(container_id):
        raise ValueError(f"invalid Docker container ID: {container_id!r}")
    matches = [
        container
        for container in containers
        if container.id.startswith(container_id)
        or container_id.startswith(container.id)
    ]
    if len(matches) > 1:
        raise ValueError(f"ambiguous Docker container ID: {container_id}")
    return matches[0] if matches else None
