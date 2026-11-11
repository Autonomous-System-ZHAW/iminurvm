import os
import subprocess
import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from gpuboard_agent import motd
from gpuboard_agent.cli.status import StatusBoard, StatusRow
from gpuboard_agent.config import load_agent_config
from gpuboard_collector import web
from gpuboard_collector.merge import merge
from gpuboard_collector.web import BoardStore, make_server
from gpuboard_common.models import GpuProcess, Session, VmInventory, VmStatus
from tests.conftest import NOW, make_claim, make_snapshot


def board_and_row(claim=None):
    snapshot = make_snapshot(
        claim=claim,
        sessions=(Session("alice"), Session("bob", "vscode")),
        gpu_processes=(GpuProcess(1, "root", container_owner="alice"),),
    )
    row = StatusRow(
        111, "simulation", "node", VmStatus.CLAIMED, "FRESH", snapshot, None
    )
    return StatusBoard(NOW.isoformat(), NOW.isoformat(), "FRESH", (row,)), row


def test_banner_claim_and_other_user_warning():
    claim = replace(make_claim(), message="hello\n\x1b[31mworld")
    board, row = board_and_row(claim)
    result = motd.render_motd(board, row, "bob")
    for text in (
        "VM 111",
        "CLAIMED",
        "Board: FRESH | snapshot: FRESH",
        "Claim (active at assessment): alice",
        "project: proj",
        "WARNING: observed claim belongs to alice",
        "Sessions: alice, bob | GPU users: alice",
        "Message: hello  [31mworld",
        "VM observed:",
    ):
        assert text in result
    assert "\x1b" not in result
    assert "observed claim belongs" not in motd.render_motd(board, row, "alice")


def test_expired_planned_and_stale_observations():
    from datetime import timedelta

    for claim, label in (
        (make_claim(end=timedelta(seconds=-1)), "expired"),
        (make_claim(start=timedelta(hours=1)), "planned"),
    ):
        board, row = board_and_row(claim)
        board = replace(board, freshness="STALE")
        row = replace(row, freshness="CLOCK_WARNING")
        output = motd.render_motd(board, row, "bob")
        assert f"Claim ({label} at assessment)" in output
        assert "WARNING: collector information may be stale or unavailable." in output
        assert "observed claim belongs to alice" in output


def test_missing_snapshot_and_no_claim():
    board, row = board_and_row()
    assert "Claim: none observed" in motd.render_motd(board, row, "alice")
    row = replace(row, snapshot=None, freshness="UNAVAILABLE", error="failed")
    output = motd.render_motd(board, row, "alice")
    assert "do not assume the VM is free" in output
    assert "Collector error: failed" in output
    assert "Claim: none" not in output


@pytest.mark.parametrize("value", ["0", "-1", "true", "'111'", "null"])
def test_invalid_vmid(tmp_path, value):
    path = tmp_path / "config.yaml"
    path.write_text(f"vmid: {value}\n")
    with pytest.raises(ValueError, match="vmid"):
        load_agent_config(path)


def test_main_config_and_missing_row(tmp_path, monkeypatch, capsys):
    path = tmp_path / "agent.yaml"
    path.write_text("collector_status_url: http://localhost/status.json\nvmid: 111\n")
    board, _ = board_and_row(make_claim())
    monkeypatch.setattr(motd, "fetch_status", Mock(return_value=(board, {})))
    monkeypatch.setattr(motd, "current_user", Mock(return_value="bob"))
    assert motd.main(["--config", str(path)]) == 0
    assert "observed claim belongs to alice" in capsys.readouterr().out
    path.write_text("collector_status_url: http://localhost/status.json\nvmid: 112\n")
    assert motd.main(["--config", str(path)]) == 1
    assert "VM 112 not found" in capsys.readouterr().err
    path.write_text("{}\n")
    assert motd.main(["--config", str(path)]) == 1
    assert "set vmid" in capsys.readouterr().err


def test_fetch_failure_is_visible(tmp_path, monkeypatch, capsys):
    path = tmp_path / "agent.yaml"
    path.write_text("collector_status_url: http://localhost/status.json\nvmid: 111\n")
    monkeypatch.setattr(motd, "fetch_status", Mock(side_effect=ValueError("HTTP 503")))
    assert motd.main(["--config", str(path)]) == 1
    assert "status unavailable: HTTP 503" in capsys.readouterr().err


def test_banner_against_http_endpoint(tmp_path, monkeypatch, capsys):
    store = BoardStore(30)
    store.set_board(
        merge(
            [VmInventory(111, "simulation", "node", True)],
            {111: make_snapshot(claim=make_claim())},
            NOW,
        )
    )
    monkeypatch.setattr(web, "now", lambda: NOW)
    monkeypatch.setattr(motd, "current_user", lambda: "bob")
    server = make_server("127.0.0.1", 0, store)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    path = tmp_path / "agent.yaml"
    path.write_text(
        f"collector_status_url: http://127.0.0.1:{server.server_port}/status.json\n"
        "vmid: 111\n"
    )
    try:
        assert motd.main(["--config", str(path)]) == 0
        assert "observed claim belongs to alice" in capsys.readouterr().out
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_profile_hook_interactive_once_and_noninteractive_skipped(tmp_path):
    script = Path("motd/gpuboard-motd.sh").read_text()
    executable = tmp_path / "vm-motd"
    executable.write_text("#!/bin/sh\nprintf 'BANNER\\n'\n")
    executable.chmod(0o755)
    hook = tmp_path / "hook.sh"
    hook.write_text(script.replace("/opt/gpuboard/venv/bin/vm-motd", str(executable)))
    env = {**os.environ, "GPUBOARD_MOTD_SHOWN": ""}
    cmd = f'. "{hook}"; . "{hook}"; echo READY'
    interactive = subprocess.run(
        ["bash", "--noprofile", "--norc", "-ic", cmd],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert interactive.returncode == 0
    assert interactive.stdout.count("BANNER") == 1
    assert "READY" in interactive.stdout
    noninteractive = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", cmd],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert noninteractive.returncode == 0
    assert "BANNER" not in noninteractive.stdout
    child = subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-ic",
            f'. "{hook}"; bash --noprofile --norc -ic \'. "{hook}"\'',
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert child.returncode == 0
    assert child.stdout.count("BANNER") == 2


def test_profile_timeout_does_not_block_shell(tmp_path):
    script = Path("motd/gpuboard-motd.sh").read_text()
    executable = tmp_path / "vm-motd"
    executable.write_text("#!/bin/sh\nexec sleep 10\n")
    executable.chmod(0o755)
    hook = tmp_path / "hook.sh"
    hook.write_text(script.replace("/opt/gpuboard/venv/bin/vm-motd", str(executable)))
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-iec", f'. "{hook}"; echo READY'],
        capture_output=True,
        text=True,
        env={**os.environ, "GPUBOARD_MOTD_SHOWN": ""},
        timeout=6,
    )
    assert result.returncode == 0
    assert "READY" in result.stdout
    assert "request timed out" in result.stderr
