import json
import pwd
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from gpuboard_agent import gpu, main, sessions
from gpuboard_agent.config import AgentConfig, load_agent_config
from gpuboard_common.models import Container, GpuProcess, Session, VmSnapshot
from gpuboard_common.serialize import snapshot_from_dict, snapshot_to_dict
from tests.conftest import make_claim


def full_snapshot() -> VmSnapshot:
    now = datetime(2026, 11, 9, 10, 0, 0, 123456, tzinfo=UTC)
    claim = replace(
        make_claim(), start=now, end=now + timedelta(hours=4), created_at=now
    )
    return VmSnapshot(
        hostname="gpu-101",
        collected_at=now,
        gpu_model="GPU",
        sessions=(Session("alice", "ssh", "pts/0", "client", now),),
        containers=(Container("abc123", "sim", "image", "Up", {"owner": "alice"}),),
        gpu_processes=(
            GpuProcess(
                1, "root", "python", 42, "GPU-x", "abc123", "sim", "alice", "proj"
            ),
        ),
        claim=claim,
    )


def test_snapshot_json_roundtrip() -> None:
    snapshot = full_snapshot()
    data = snapshot_to_dict(snapshot)
    assert data["schema_version"] == 1
    assert snapshot_from_dict(json.loads(json.dumps(data))) == snapshot


def test_snapshot_empty_roundtrip() -> None:
    snapshot = VmSnapshot("gpu", datetime.now(UTC))
    assert snapshot_from_dict(snapshot_to_dict(snapshot)) == snapshot


def test_snapshot_roundtrip_with_unmapped_uids() -> None:
    snapshot = replace(
        full_snapshot(),
        sessions=(Session("uid:1234", "vscode"),),
        gpu_processes=(GpuProcess(42, "uid:1234", "kit"),),
    )
    assert snapshot_from_dict(json.loads(json.dumps(snapshot_to_dict(snapshot)))) == (
        snapshot
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("hostname", ""),
        ("collected_at", "2026-01-01T00:00:00"),
        ("sessions", None),
        ("containers", {}),
        ("gpu_processes", "invalid"),
        ("claim", []),
    ],
)
def test_snapshot_rejects_invalid_fields(field: str, value: object) -> None:
    data = snapshot_to_dict(full_snapshot())
    data[field] = value
    with pytest.raises(ValueError):
        snapshot_from_dict(data)


def test_snapshot_rejects_invalid_nested_fields() -> None:
    data = snapshot_to_dict(full_snapshot())
    data["gpu_processes"][0]["pid"] = True
    with pytest.raises(ValueError):
        snapshot_from_dict(data)
    data = snapshot_to_dict(full_snapshot())
    data["sessions"][0]["kind"] = "unknown"
    with pytest.raises(ValueError):
        snapshot_from_dict(data)
    data = snapshot_to_dict(full_snapshot())
    data["containers"][0]["labels"] = {"owner": 42}
    with pytest.raises(ValueError):
        snapshot_from_dict(data)
    data = snapshot_to_dict(full_snapshot())
    data["claim"]["owner"] = None
    with pytest.raises(ValueError):
        snapshot_from_dict(data)


def test_snapshot_rejects_naive_serialization() -> None:
    with pytest.raises(ValueError, match="offset"):
        snapshot_to_dict(replace(full_snapshot(), collected_at=datetime(2026, 1, 1)))


def test_config_example() -> None:
    config = load_agent_config(Path("agent/agent.example.yaml"))
    assert config == AgentConfig()


def test_config_defaults_and_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gpuboard_agent import config

    monkeypatch.setattr(config, "DEFAULT_CONFIG_PATH", tmp_path / "missing.yaml")
    assert load_agent_config() == AgentConfig()
    with pytest.raises(FileNotFoundError):
        load_agent_config(tmp_path / "missing.yaml")
    path = tmp_path / "agent.yaml"
    path.write_text(
        "claim_path: /tmp/claim.json\npam_auto_claim_enabled: false\n"
        "idle_grace_minutes: 0\nexcluded_session_users: [gpuboard, collector]\n",
        encoding="utf-8",
    )
    loaded = load_agent_config(path)
    assert loaded.claim_path == Path("/tmp/claim.json")
    assert loaded.pam_auto_claim_enabled is False
    assert loaded.idle_grace_minutes == 0
    assert loaded.auto_claim_hours == 4
    assert loaded.excluded_session_users == ("gpuboard", "collector")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[]",
        "unknown: 1",
        "claim_path: relative",
        "pam_auto_claim_enabled: 42",
        "auto_claim_hours: 0",
        "auto_claim_hours: true",
        "idle_grace_minutes: -1",
        "default_claim_hours: .inf",
        "excluded_session_users: gpuboard",
        "excluded_session_users: null",
        "excluded_session_users: [gpuboard, gpuboard]",
        "excluded_session_users: [null]",
        "excluded_session_users: ['']",
        "excluded_session_users: [' gpuboard']",
        "excluded_session_users: ['gpu board']",
        "x: [",
    ],
)
def test_bad_config(tmp_path: Path, text: str) -> None:
    path = tmp_path / "agent.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_agent_config(path)


def test_build_snapshot_wires_collectors(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = full_snapshot()
    config = AgentConfig()
    containers = list(sample.containers)
    monkeypatch.setattr(main, "load_agent_config", Mock(return_value=config))
    monkeypatch.setattr(
        main, "list_login_sessions", Mock(return_value=list(sample.sessions))
    )
    monkeypatch.setattr(main, "find_vscode_users", Mock(return_value={"bob"}))
    monkeypatch.setattr(main, "list_containers", Mock(return_value=containers))
    gpu = Mock(return_value=list(sample.gpu_processes))
    monkeypatch.setattr(main, "list_gpu_processes", gpu)
    monkeypatch.setattr(main, "read_gpu_model", Mock(return_value=sample.gpu_model))
    monkeypatch.setattr(main, "load_claim", Mock(return_value=sample.claim))
    monkeypatch.setattr(main.socket, "gethostname", Mock(return_value=sample.hostname))
    monkeypatch.setattr(main, "now", Mock(return_value=sample.collected_at))
    actual = main.build_snapshot()
    assert actual == replace(
        sample, sessions=sample.sessions + (Session("bob", "vscode"),)
    )
    gpu.assert_called_once_with(containers)
    main.load_claim.assert_called_once_with(config.claim_path)


def test_snapshot_excludes_only_configured_session_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AgentConfig(excluded_session_users=("gpuboard",))
    monkeypatch.setattr(main, "load_agent_config", Mock(return_value=config))
    monkeypatch.setattr(
        main,
        "list_login_sessions",
        Mock(return_value=[Session("gpuboard"), Session("alice")]),
    )
    monkeypatch.setattr(
        main, "find_vscode_users", Mock(return_value={"gpuboard", "alice"})
    )
    monkeypatch.setattr(main, "list_containers", Mock(return_value=[]))
    monkeypatch.setattr(main, "read_gpu_model", Mock(return_value="GPU"))
    gpu_process = GpuProcess(42, "gpuboard", "kit")
    monkeypatch.setattr(main, "list_gpu_processes", Mock(return_value=[gpu_process]))
    monkeypatch.setattr(main, "load_claim", Mock(return_value=None))
    snapshot = main.build_snapshot()
    assert snapshot.sessions == (Session("alice"), Session("alice", "vscode"))
    assert snapshot.gpu_processes == (gpu_process,)


def test_main_emits_only_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(main, "build_snapshot", Mock(return_value=full_snapshot()))
    assert main.main(["--config", "/tmp/agent.yaml"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert snapshot_from_dict(json.loads(output.out)) == full_snapshot()
    main.build_snapshot.assert_called_once_with(Path("/tmp/agent.yaml"))


def test_main_emits_snapshot_with_unmapped_container_uid(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    container_id = "a" * 64
    container = Container(container_id, "isaac-sim")
    monkeypatch.setattr(main, "load_agent_config", Mock(return_value=AgentConfig()))
    monkeypatch.setattr(main, "list_login_sessions", Mock(return_value=[]))
    monkeypatch.setattr(main, "list_containers", Mock(return_value=[container]))
    monkeypatch.setattr(main, "read_gpu_model", Mock(return_value="GPU"))
    monkeypatch.setattr(main, "load_claim", Mock(return_value=None))
    monkeypatch.setattr(gpu, "query_compute_apps", lambda: "42, kit, GPU-x, 4451\n")
    monkeypatch.setattr(
        gpu.Path, "read_text", Mock(return_value=f"0::/docker/{container_id}\n")
    )
    responses = [
        subprocess.CompletedProcess(
            [], 0, stdout="1234 /home/user/.vscode-server/bin/node\n"
        ),
        subprocess.CompletedProcess([], 0, stdout="1234\n"),
    ]
    monkeypatch.setattr(sessions.subprocess, "run", Mock(side_effect=responses))
    monkeypatch.setattr(pwd, "getpwuid", Mock(side_effect=KeyError(1234)))

    assert main.main([]) == 0
    output = capsys.readouterr()
    snapshot = snapshot_from_dict(json.loads(output.out))
    assert snapshot.sessions == (Session("uid:1234", "vscode"),)
    assert snapshot.gpu_processes[0].user == "uid:1234"
    assert snapshot.gpu_processes[0].container == "isaac-sim"
    assert "UID 1234 has no host username" in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        ValueError("broken"),
        FileNotFoundError("missing"),
        subprocess.TimeoutExpired("ps", 10),
    ],
)
def test_main_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    monkeypatch.setattr(main, "build_snapshot", Mock(side_effect=error))
    assert main.main([]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "vm-agent:" in output.err


def test_entry_point_reports_missing_config(tmp_path: Path) -> None:
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from gpuboard_agent.main import main; raise SystemExit(main())",
            "--config",
            str(tmp_path / "missing.yaml"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "vm-agent:" in result.stderr
