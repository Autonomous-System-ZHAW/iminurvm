import json
import subprocess
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from gpuboard_collector.config import CollectorConfig
from gpuboard_collector.ssh_pull import build_ssh_command, pull_all, pull_snapshot
from gpuboard_common.models import VmInventory, VmSnapshot
from gpuboard_common.serialize import snapshot_to_dict

CONFIG = CollectorConfig()
VM = VmInventory(111, "simulation", "pve", True, address="10.0.0.111")
SNAPSHOT = VmSnapshot("vm111", datetime(2026, 11, 11, tzinfo=UTC))


def test_ssh_arguments_are_noninteractive_and_verify_host_keys() -> None:
    command = build_ssh_command(CONFIG, "10.0.0.111")
    assert command == [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-i",
        str(CONFIG.ssh_key),
        "-l",
        "gpuboard",
        "--",
        "10.0.0.111",
        "vm-agent",
    ]


def test_remote_command_is_a_single_quoted_executable() -> None:
    config = CollectorConfig(agent_command="/opt/agent; echo unsafe")
    assert build_ssh_command(config, "vm")[-1] == "'/opt/agent; echo unsafe'"


@pytest.mark.parametrize("address", ["", "-oProxyCommand=bad", "one host"])
def test_invalid_address(address: str) -> None:
    with pytest.raises(ValueError):
        build_ssh_command(CONFIG, address)


def test_valid_snapshot_and_stderr(monkeypatch, caplog) -> None:
    run = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(snapshot_to_dict(SNAPSHOT)), stderr="UID warning"
        )
    )
    monkeypatch.setattr(subprocess, "run", run)
    assert pull_snapshot(CONFIG, VM) == SNAPSHOT
    assert "UID warning" in caplog.text
    assert run.call_args.kwargs["timeout"] == 10
    assert run.call_args.kwargs["check"] is False


@pytest.mark.parametrize("text", ["not json", "[]", '{"schema_version": 2}', ""])
def test_invalid_snapshot_rejected(monkeypatch, text: str) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 0, text, "")),
    )
    with pytest.raises(ValueError):
        pull_snapshot(CONFIG, VM)


def test_remote_error_includes_stderr(monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 1, "", "agent failed")),
    )
    with pytest.raises(RuntimeError, match="agent failed"):
        pull_snapshot(CONFIG, VM)


def test_timeout_and_missing_address(monkeypatch) -> None:
    run = Mock(side_effect=subprocess.TimeoutExpired("ssh", 10))
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.TimeoutExpired):
        pull_snapshot(CONFIG, VM)
    with pytest.raises(ValueError, match="no configured SSH address"):
        pull_snapshot(CONFIG, VmInventory(222, "x", "pve", True))
    with pytest.raises(ValueError, match="stopped"):
        pull_snapshot(CONFIG, VmInventory(222, "x", "pve", False))
    assert run.call_count == 1


def test_pull_all_retains_per_vm_errors_and_skips_stopped(monkeypatch) -> None:
    from gpuboard_collector import ssh_pull

    failed = VmInventory(112, "bad", "pve", True, address="bad")
    stopped = VmInventory(113, "off", "pve", False)

    def observe(config, vm):
        if vm.vmid == 111:
            return SNAPSHOT
        raise ValueError("failed")

    run = Mock(side_effect=observe)
    monkeypatch.setattr(ssh_pull, "pull_snapshot", run)
    results = pull_all(CONFIG, [VM, failed, stopped])
    assert results[111] == SNAPSHOT
    assert isinstance(results[112], ValueError)
    assert 113 not in results
    assert run.call_count == 2


def test_duplicate_ids_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        pull_all(CONFIG, [VM, VM])
