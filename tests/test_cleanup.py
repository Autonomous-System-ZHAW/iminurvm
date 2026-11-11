import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest

from gpuboard_agent import cleanup
from gpuboard_agent.cli import extend
from gpuboard_agent.config import AgentConfig
from gpuboard_common.claimfile import load_claim, save_claim
from gpuboard_common.models import Session
from tests.conftest import NOW, make_claim


@pytest.fixture
def setup_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    config = AgentConfig(claim_path=tmp_path / "claim.json", idle_grace_minutes=30)
    monkeypatch.setattr(cleanup, "list_login_sessions", Mock(return_value=[]))
    monkeypatch.setattr(cleanup, "find_vscode_users", Mock(return_value=set()))
    monkeypatch.setattr(cleanup, "query_compute_apps", Mock(return_value=""))
    return config


@pytest.mark.parametrize("end_minutes", [60, 0, -29])
def test_not_due_keeps_claim_without_observations(
    setup_cleanup: AgentConfig, end_minutes: int
) -> None:
    claim = make_claim(start=timedelta(hours=-3), end=timedelta(minutes=end_minutes))
    save_claim(setup_cleanup.claim_path, claim)
    assert not cleanup.cleanup_expired_claim(setup_cleanup, NOW)
    assert load_claim(setup_cleanup.claim_path) == claim
    cleanup.list_login_sessions.assert_not_called()
    cleanup.find_vscode_users.assert_not_called()
    cleanup.query_compute_apps.assert_not_called()


def test_no_claim_does_not_observe(setup_cleanup: AgentConfig) -> None:
    assert not cleanup.cleanup_expired_claim(setup_cleanup, NOW)
    cleanup.list_login_sessions.assert_not_called()


def test_zero_grace_removes_at_expiry(setup_cleanup: AgentConfig) -> None:
    config = AgentConfig(claim_path=setup_cleanup.claim_path, idle_grace_minutes=0)
    save_claim(
        config.claim_path,
        make_claim(start=timedelta(hours=-1), end=timedelta(0)),
    )
    assert cleanup.cleanup_expired_claim(config, NOW)
    assert load_claim(config.claim_path) is None


@pytest.mark.parametrize("end_minutes", [-30, -120])
def test_due_and_idle_removes_claim(
    setup_cleanup: AgentConfig, end_minutes: int
) -> None:
    claim = make_claim(start=timedelta(hours=-4), end=timedelta(minutes=end_minutes))
    save_claim(setup_cleanup.claim_path, claim)
    assert cleanup.cleanup_expired_claim(setup_cleanup, NOW)
    assert load_claim(setup_cleanup.claim_path) is None


@pytest.mark.parametrize("activity", ["session", "vscode", "gpu"])
def test_activity_keeps_claim(setup_cleanup: AgentConfig, activity: str) -> None:
    claim = make_claim(start=timedelta(hours=-3), end=timedelta(hours=-1))
    save_claim(setup_cleanup.claim_path, claim)
    if activity == "session":
        cleanup.list_login_sessions.return_value = [Session("bob")]
    elif activity == "vscode":
        cleanup.find_vscode_users.return_value = {"bob"}
    else:
        cleanup.query_compute_apps.return_value = "1234, kit, GPU-x, 42\n"
    assert not cleanup.cleanup_expired_claim(setup_cleanup, NOW)
    assert load_claim(setup_cleanup.claim_path) == claim


def test_only_excluded_sessions_do_not_prevent_cleanup(
    setup_cleanup: AgentConfig,
) -> None:
    config = replace(setup_cleanup, excluded_session_users=("gpuboard",))
    save_claim(
        config.claim_path,
        make_claim(start=timedelta(hours=-3), end=timedelta(hours=-1)),
    )
    cleanup.list_login_sessions.return_value = [Session("gpuboard")]
    cleanup.find_vscode_users.return_value = {"gpuboard"}
    assert cleanup.cleanup_expired_claim(config, NOW)
    assert load_claim(config.claim_path) is None


@pytest.mark.parametrize("kind", ["ssh", "vscode", "gpu"])
def test_other_activity_still_prevents_cleanup(
    setup_cleanup: AgentConfig, kind: str
) -> None:
    config = replace(setup_cleanup, excluded_session_users=("gpuboard",))
    claim = make_claim(start=timedelta(hours=-3), end=timedelta(hours=-1))
    save_claim(config.claim_path, claim)
    cleanup.list_login_sessions.return_value = [Session("gpuboard")]
    cleanup.find_vscode_users.return_value = {"gpuboard"}
    if kind == "ssh":
        cleanup.list_login_sessions.return_value.append(Session("alice"))
    elif kind == "vscode":
        cleanup.find_vscode_users.return_value.add("alice")
    else:
        cleanup.query_compute_apps.return_value = "1234, kit, GPU-x, 42\n"
    assert not cleanup.cleanup_expired_claim(config, NOW)
    assert load_claim(config.claim_path) == claim


@pytest.mark.parametrize(
    "source", ["list_login_sessions", "find_vscode_users", "query_compute_apps"]
)
def test_failed_observation_keeps_claim(
    setup_cleanup: AgentConfig, source: str
) -> None:
    claim = make_claim(start=timedelta(hours=-3), end=timedelta(hours=-1))
    save_claim(setup_cleanup.claim_path, claim)
    getattr(cleanup, source).side_effect = subprocess.CalledProcessError(1, source)
    with pytest.raises(subprocess.CalledProcessError):
        cleanup.cleanup_expired_claim(setup_cleanup, NOW)
    assert load_claim(setup_cleanup.claim_path) == claim


def test_excluded_login_does_not_hide_vscode_check_failure(
    setup_cleanup: AgentConfig,
) -> None:
    config = replace(setup_cleanup, excluded_session_users=("gpuboard",))
    claim = make_claim(start=timedelta(hours=-3), end=timedelta(hours=-1))
    save_claim(config.claim_path, claim)
    cleanup.list_login_sessions.return_value = [Session("gpuboard")]
    cleanup.find_vscode_users.side_effect = subprocess.CalledProcessError(1, "ps")
    with pytest.raises(subprocess.CalledProcessError):
        cleanup.cleanup_expired_claim(config, NOW)
    assert load_claim(config.claim_path) == claim


def test_invalid_gpu_output_keeps_claim(setup_cleanup: AgentConfig) -> None:
    claim = make_claim(start=timedelta(hours=-3), end=timedelta(hours=-1))
    save_claim(setup_cleanup.claim_path, claim)
    cleanup.query_compute_apps.return_value = "bad output"
    with pytest.raises(ValueError):
        cleanup.cleanup_expired_claim(setup_cleanup, NOW)
    assert load_claim(setup_cleanup.claim_path) == claim


def test_cleanup_respects_concurrent_extension(
    setup_cleanup: AgentConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim = make_claim(start=timedelta(hours=-3), end=timedelta(hours=-1))
    save_claim(setup_cleanup.claim_path, claim)
    observing = Event()
    continue_check = Event()
    extending = Event()

    def observe() -> list[Session]:
        observing.set()
        assert continue_check.wait(timeout=5)
        return [Session("alice")]

    monkeypatch.setattr(cleanup, "list_login_sessions", observe)
    monkeypatch.setattr(extend, "load_agent_config", lambda path: setup_cleanup)
    monkeypatch.setattr(extend, "current_user", lambda: "alice")
    monkeypatch.setattr(extend, "now", lambda: NOW)

    def do_extend() -> int:
        extending.set()
        return extend.main(["2h"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        cleanup_result = executor.submit(
            cleanup.cleanup_expired_claim, setup_cleanup, NOW
        )
        try:
            assert observing.wait(timeout=5)
            extension = executor.submit(do_extend)
            assert extending.wait(timeout=5)
        finally:
            continue_check.set()
        assert not cleanup_result.result(timeout=5)
        assert extension.result(timeout=5) == 0
    updated = load_claim(setup_cleanup.claim_path)
    assert updated is not None
    assert updated.end == NOW + timedelta(hours=2)
    assert not cleanup.cleanup_expired_claim(setup_cleanup, NOW)


def test_main_reports_observation_error(
    setup_cleanup: AgentConfig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    claim = make_claim(start=timedelta(hours=-3), end=timedelta(hours=-1))
    save_claim(setup_cleanup.claim_path, claim)
    monkeypatch.setattr(cleanup, "load_agent_config", lambda path: setup_cleanup)
    monkeypatch.setattr(cleanup, "current_time", lambda: NOW)
    cleanup.query_compute_apps.side_effect = subprocess.CalledProcessError(
        1, "nvidia-smi"
    )
    assert cleanup.main(["--config", "/test/agent.yaml"]) == 1
    assert "vm-cleanup:" in capsys.readouterr().err
    assert load_claim(setup_cleanup.claim_path) == claim


def test_main_removed_and_noop(
    setup_cleanup: AgentConfig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cleanup, "load_agent_config", lambda path: setup_cleanup)
    monkeypatch.setattr(cleanup, "current_time", lambda: NOW)
    save_claim(
        setup_cleanup.claim_path,
        make_claim(start=timedelta(hours=-3), end=timedelta(hours=-1)),
    )
    assert cleanup.main([]) == 0
    assert "Expired claim removed" in capsys.readouterr().out
    assert cleanup.main([]) == 0
    assert "No claim removed" in capsys.readouterr().out
