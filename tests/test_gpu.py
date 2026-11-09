import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from gpuboard_agent import gpu
from gpuboard_common.models import Container, GpuProcess

UUID = "GPU-11111111-2222-3333-4444-555555555555"
ID = "3f4a9c1b2d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f9012345678901234ab"


def completed(text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout=text, stderr="")


def test_parse_fixture(fixtures_dir: Path) -> None:
    text = (fixtures_dir / "nvidia_smi_compute_apps.csv").read_text()
    assert gpu.parse_compute_apps_csv(text) == [
        GpuProcess(4242, "", "/isaac-sim/kit/python/bin/python3", 18432, UUID),
        GpuProcess(5150, "", "blender", 2048, UUID),
    ]


def test_parse_no_header_and_quoted_name() -> None:
    result = gpu.parse_compute_apps_csv(f'12, "process, name", {UUID}, 0\n')
    assert result == [GpuProcess(12, "", "process, name", 0, UUID)]
    assert gpu.parse_compute_apps_csv("") == []


@pytest.mark.parametrize("value", ["N/A", "[N/A]", "Not Supported", "[Not Supported]"])
def test_unavailable_memory(value: str) -> None:
    assert (
        gpu.parse_compute_apps_csv(f"1, python, {UUID}, {value}")[0].gpu_memory_mib
        is None
    )


@pytest.mark.parametrize(
    "text",
    [
        "1, python",
        "0, python, GPU-x, 1",
        "-1, python, GPU-x, 1",
        "notpid, python, GPU-x, 1",
        "1, , GPU-x, 1",
        "1, python, , 1",
        "1, python, GPU-x, -1",
        "1, python, GPU-x, unknown",
        '1, "unterminated',
    ],
)
def test_parse_invalid_rows(text: str) -> None:
    with pytest.raises(ValueError):
        gpu.parse_compute_apps_csv(text)


def test_query_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(
        side_effect=[completed("GPU model\n"), completed(f"1, python, {UUID}, 4\n")]
    )
    monkeypatch.setattr(gpu.subprocess, "run", run)
    assert gpu.read_gpu_model() == "GPU model"
    assert gpu.query_compute_apps() == f"1, python, {UUID}, 4\n"
    assert run.call_args_list[0].args[0] == [
        "nvidia-smi",
        "--query-gpu=name",
        "--format=csv,noheader",
    ]
    assert run.call_args_list[1].args[0] == [
        "nvidia-smi",
        "--query-compute-apps=pid,process_name,gpu_uuid,used_gpu_memory",
        "--format=csv,noheader,nounits",
    ]
    for call in run.call_args_list:
        assert call.kwargs == {
            "capture_output": True,
            "text": True,
            "check": True,
            "timeout": 10,
        }


def test_model_empty_and_multiple(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(side_effect=[completed(""), completed("GPU 1\nGPU 2\n")])
    monkeypatch.setattr(gpu.subprocess, "run", run)
    assert gpu.read_gpu_model() is None
    with pytest.raises(ValueError, match="one GPU"):
        gpu.read_gpu_model()


def test_command_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    error = subprocess.CalledProcessError(1, ["nvidia-smi"])
    monkeypatch.setattr(gpu.subprocess, "run", Mock(side_effect=error))
    with pytest.raises(subprocess.CalledProcessError):
        gpu.query_compute_apps()
    with pytest.raises(subprocess.CalledProcessError):
        gpu.read_gpu_model()


def test_resolve_process_user(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(return_value=completed("1001\n"))
    monkeypatch.setattr(gpu.subprocess, "run", run)
    monkeypatch.setattr(gpu.pwd, "getpwuid", Mock(return_value=Mock(pw_name="alice")))
    assert gpu.resolve_process_user(42) == "alice"
    run.assert_called_once_with(
        ["ps", "-p", "42", "-o", "euid="],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )


@pytest.mark.parametrize("output", ["", "bob\n", "1000\n1001\n", "-1"])
def test_resolve_invalid_uid(monkeypatch: pytest.MonkeyPatch, output: str) -> None:
    monkeypatch.setattr(gpu.subprocess, "run", Mock(return_value=completed(output)))
    with pytest.raises(ValueError):
        gpu.resolve_process_user(42)


def test_resolve_failed_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gpu.subprocess,
        "run",
        Mock(side_effect=subprocess.CalledProcessError(1, ["ps"])),
    )
    with pytest.raises(subprocess.CalledProcessError):
        gpu.resolve_process_user(42)
    with pytest.raises(ValueError):
        gpu.resolve_process_user(0)


def test_list_gpu_processes_with_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gpu,
        "query_compute_apps",
        lambda: f"42, python, {UUID}, 100\n43, blender, {UUID}, 50\n",
    )
    monkeypatch.setattr(
        gpu, "resolve_process_user", lambda pid: {42: "root", 43: "bob"}[pid]
    )
    read = Mock(side_effect=[f"0::/docker/{ID}\n", "0::/user.slice/user-1000.slice\n"])
    monkeypatch.setattr(gpu.Path, "read_text", read)
    containers = [Container(ID, "sim", labels={"owner": "alice", "project": "demo"})]
    result = gpu.list_gpu_processes(containers)
    assert result == [
        GpuProcess(42, "root", "python", 100, UUID, ID, "sim", "alice", "demo"),
        GpuProcess(43, "bob", "blender", 50, UUID),
    ]
    assert result[0].effective_owner == "alice"
    assert read.call_count == 2


def test_missing_container_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu, "query_compute_apps", lambda: f"42, python, {UUID}, 100\n")
    monkeypatch.setattr(gpu, "resolve_process_user", lambda pid: "root")
    monkeypatch.setattr(gpu.Path, "read_text", Mock(return_value=f"0::/docker/{ID}\n"))
    with pytest.raises(ValueError, match="not found in inventory"):
        gpu.list_gpu_processes([])


def test_missing_proc_cgroup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu, "query_compute_apps", lambda: f"42, python, {UUID}, 100\n")
    monkeypatch.setattr(gpu, "resolve_process_user", lambda pid: "alice")
    monkeypatch.setattr(gpu.Path, "read_text", Mock(side_effect=FileNotFoundError()))
    with pytest.raises(FileNotFoundError):
        gpu.list_gpu_processes([])


def test_list_gpu_processes_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu, "query_compute_apps", lambda: "")
    monkeypatch.setattr(gpu, "resolve_process_user", Mock())
    assert gpu.list_gpu_processes([]) == []
    gpu.resolve_process_user.assert_not_called()
