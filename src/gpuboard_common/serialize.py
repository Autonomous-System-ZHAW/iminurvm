"""JSON (de)serialization of snapshots and board state."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, cast, get_args

from gpuboard_common.claimfile import claim_from_dict, claim_to_dict
from gpuboard_common.models import (
    BoardState,
    Container,
    GpuProcess,
    Session,
    SessionKind,
    VmSnapshot,
)
from gpuboard_common.timeutil import parse_iso

SNAPSHOT_SCHEMA_VERSION = 1
BOARD_SCHEMA_VERSION = 1


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("snapshot timestamps must include an offset")
    return value.isoformat()


def _object(value: object, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{context} must be an object with fields {sorted(keys)}")
    return value


def _string(value: object, context: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a string")
    return value


def _required_string(value: object, context: str) -> str:
    result = _string(value, context)
    if not result:
        raise ValueError(f"{context} must not be empty")
    return result


def _array(value: object, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    return value


def _integer(value: object, context: str, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value


def snapshot_to_dict(snapshot: VmSnapshot) -> dict[str, Any]:
    """Convert an agent snapshot into the version 1 JSON-compatible contract."""
    claim = None
    if snapshot.claim is not None:
        claim = claim_to_dict(snapshot.claim)
        claim.update(
            start=_timestamp(snapshot.claim.start),
            end=_timestamp(snapshot.claim.end),
            created_at=_timestamp(snapshot.claim.created_at),
        )
    data = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "hostname": snapshot.hostname,
        "collected_at": _timestamp(snapshot.collected_at),
        "gpu_model": snapshot.gpu_model,
        "sessions": [
            {
                **asdict(session),
                "since": _timestamp(session.since) if session.since else None,
            }
            for session in snapshot.sessions
        ],
        "gpu_processes": [asdict(process) for process in snapshot.gpu_processes],
        "containers": [asdict(container) for container in snapshot.containers],
        "claim": claim,
    }
    snapshot_from_dict(data)
    return data


def snapshot_from_dict(data: dict[str, Any]) -> VmSnapshot:
    """Validate and decode a version 1 agent snapshot; reject unknown schemas."""
    data = _object(
        data,
        {
            "schema_version",
            "hostname",
            "collected_at",
            "gpu_model",
            "sessions",
            "gpu_processes",
            "containers",
            "claim",
        },
        "snapshot",
    )
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported snapshot schema_version")
    sessions: list[Session] = []
    for item in _array(data["sessions"], "sessions"):
        row = _object(item, {"user", "kind", "tty", "remote_host", "since"}, "session")
        kind = _required_string(row["kind"], "session.kind")
        if kind not in get_args(SessionKind):
            raise ValueError(f"invalid session.kind: {kind}")
        since = _string(row["since"], "session.since", nullable=True)
        sessions.append(
            Session(
                user=_required_string(row["user"], "session.user"),
                kind=cast(SessionKind, kind),
                tty=_string(row["tty"], "session.tty", nullable=True),
                remote_host=_string(
                    row["remote_host"], "session.remote_host", nullable=True
                ),
                since=parse_iso(since) if since is not None else None,
            )
        )
    containers: list[Container] = []
    for item in _array(data["containers"], "containers"):
        row = _object(item, {"id", "name", "image", "status", "labels"}, "container")
        labels = row["labels"]
        if not isinstance(labels, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in labels.items()
        ):
            raise ValueError("container.labels must be a string mapping")
        containers.append(
            Container(
                id=_required_string(row["id"], "container.id"),
                name=_required_string(row["name"], "container.name"),
                image=cast(str, _string(row["image"], "container.image")),
                status=cast(str, _string(row["status"], "container.status")),
                labels=dict(labels),
            )
        )
    processes: list[GpuProcess] = []
    for item in _array(data["gpu_processes"], "gpu_processes"):
        row = _object(
            item,
            {
                "pid",
                "user",
                "name",
                "gpu_memory_mib",
                "gpu_uuid",
                "container_id",
                "container",
                "container_owner",
                "container_project",
            },
            "gpu process",
        )
        pid = _integer(row["pid"], "gpu process.pid")
        memory = _integer(
            row["gpu_memory_mib"], "gpu process.gpu_memory_mib", nullable=True
        )
        if pid is None or pid <= 0 or (memory is not None and memory < 0):
            raise ValueError("invalid GPU process PID or memory")
        processes.append(
            GpuProcess(
                pid=pid,
                user=_required_string(row["user"], "gpu process.user"),
                name=cast(str, _string(row["name"], "gpu process.name")),
                gpu_memory_mib=memory,
                gpu_uuid=_string(
                    row["gpu_uuid"], "gpu process.gpu_uuid", nullable=True
                ),
                container_id=_string(
                    row["container_id"], "gpu process.container_id", nullable=True
                ),
                container=_string(
                    row["container"], "gpu process.container", nullable=True
                ),
                container_owner=_string(
                    row["container_owner"], "gpu process.container_owner", nullable=True
                ),
                container_project=_string(
                    row["container_project"],
                    "gpu process.container_project",
                    nullable=True,
                ),
            )
        )
    claim = data["claim"]
    if claim is not None:
        claim = _object(
            claim,
            {
                "owner",
                "project",
                "message",
                "start",
                "end",
                "kind",
                "pid",
                "created_by",
                "created_at",
            },
            "claim",
        )
        for key in (
            "owner",
            "project",
            "message",
            "start",
            "end",
            "kind",
            "created_by",
            "created_at",
        ):
            _string(claim[key], f"claim.{key}")
        _integer(claim["pid"], "claim.pid", nullable=True)
    return VmSnapshot(
        hostname=_required_string(data["hostname"], "hostname"),
        collected_at=parse_iso(_required_string(data["collected_at"], "collected_at")),
        gpu_model=_string(data["gpu_model"], "gpu_model", nullable=True),
        sessions=tuple(sessions),
        containers=tuple(containers),
        gpu_processes=tuple(processes),
        claim=claim_from_dict(claim) if claim is not None else None,
    )


def board_to_dict(board: BoardState) -> dict[str, Any]:
    """Convert a board to version 1 JSON, retaining each snapshot's schema."""
    return {
        "schema_version": BOARD_SCHEMA_VERSION,
        "generated_at": _timestamp(board.generated_at),
        "vms": [
            {
                "inventory": {
                    **asdict(entry.inventory),
                    "hostpci": list(entry.inventory.hostpci),
                },
                "status": entry.status.value,
                "snapshot": (
                    snapshot_to_dict(entry.snapshot)
                    if entry.snapshot is not None
                    else None
                ),
                "error": entry.error,
            }
            for entry in board.vms
        ],
    }
