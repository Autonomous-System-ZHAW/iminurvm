"""GPU model and compute process detection."""

from __future__ import annotations

import csv
import io
import pwd
import subprocess
from dataclasses import replace
from pathlib import Path

from gpuboard_agent.docker import container_id_from_cgroup, find_container
from gpuboard_common.models import Container, GpuProcess


def read_gpu_model() -> str | None:
    """Return the single GPU's model, or None if the query returns no GPU.

    Command failures and multiple GPU models are errors, not an idle VM.
    """
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    models = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(models) > 1:
        raise ValueError("expected at most one GPU")
    return models[0] if models else None


def query_compute_apps() -> str:
    """Query compute processes as headerless CSV with memory in MiB."""
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,gpu_uuid,used_gpu_memory",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return result.stdout


def parse_compute_apps_csv(text: str) -> list[GpuProcess]:
    """Parse compute CSV, optionally including its header and MiB suffix.

    User and container details are resolved separately. Unavailable memory
    values are represented by None; invalid process rows raise ValueError.
    """
    processes: list[GpuProcess] = []
    reader = csv.reader(io.StringIO(text), skipinitialspace=True, strict=True)
    try:
        for row in reader:
            if not row or all(not field.strip() for field in row):
                continue
            row = [field.strip() for field in row]
            if not processes and row == [
                "pid",
                "process_name",
                "gpu_uuid",
                "used_gpu_memory [MiB]",
            ]:
                continue
            if len(row) != 4:
                raise ValueError(f"invalid GPU CSV row: {row!r}")
            pid_text, name, gpu_uuid, memory_text = row
            if not pid_text.isascii() or not pid_text.isdecimal() or int(pid_text) <= 0:
                raise ValueError(f"invalid GPU process PID: {pid_text!r}")
            if not name or not gpu_uuid:
                raise ValueError(f"missing GPU process name or UUID: {row!r}")
            if memory_text.endswith(" MiB"):
                memory_text = memory_text.removesuffix(" MiB").strip()
            if memory_text in {"N/A", "[N/A]", "Not Supported", "[Not Supported]"}:
                memory = None
            elif memory_text.isascii() and memory_text.isdecimal():
                memory = int(memory_text)
            else:
                raise ValueError(f"invalid GPU memory value: {memory_text!r}")
            processes.append(
                GpuProcess(
                    pid=int(pid_text),
                    user="",
                    name=name,
                    gpu_uuid=gpu_uuid,
                    gpu_memory_mib=memory,
                )
            )
    except csv.Error as exc:
        raise ValueError("invalid GPU CSV") from exc
    return processes


def resolve_process_user(pid: int) -> str:
    """Resolve the effective Linux user of a PID, or propagate lookup errors."""
    if pid <= 0:
        raise ValueError("PID must be positive")
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "euid="],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    uid = result.stdout.strip()
    if not uid.isascii() or not uid.isdecimal():
        raise ValueError(f"invalid process UID for PID {pid}: {uid!r}")
    return pwd.getpwuid(int(uid)).pw_name


def list_gpu_processes(containers: list[Container]) -> list[GpuProcess]:
    """Collect GPU processes and map each PID to a user and Docker container.

    The caller supplies the same Docker inventory used in the snapshot.
    Processes disappearing or recognized Docker IDs missing from that
    inventory raise an error instead of producing misleading ownership data.
    """
    processes = parse_compute_apps_csv(query_compute_apps())
    resolved: list[GpuProcess] = []
    for process in processes:
        user = resolve_process_user(process.pid)
        cgroup_text = Path(f"/proc/{process.pid}/cgroup").read_text(encoding="utf-8")
        container_id = container_id_from_cgroup(cgroup_text)
        container = None
        if container_id is not None:
            container = find_container(container_id, containers)
            if container is None:
                raise ValueError(
                    f"Docker container {container_id} for PID {process.pid} "
                    "not found in inventory"
                )
        resolved.append(
            replace(
                process,
                user=user,
                container_id=container_id,
                container=container.name if container else None,
                container_owner=container.owner if container else None,
                container_project=container.project if container else None,
            )
        )
    return resolved
