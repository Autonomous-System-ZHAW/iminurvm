import json
import re
import threading
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from urllib.error import URLError

import pytest

from gpuboard_agent.cli import status
from gpuboard_agent.config import load_agent_config, validate_collector_status_url
from gpuboard_collector import web
from gpuboard_collector.merge import merge
from gpuboard_collector.web import BoardStore, make_server, status_response
from gpuboard_common.models import GpuProcess, Session, VmInventory
from tests.conftest import NOW, make_claim, make_snapshot


@pytest.fixture
def payload(monkeypatch):
    claim = replace(make_claim(), message="hello\n\x1b[31mworld")
    snapshot = make_snapshot(
        claim=claim,
        sessions=(Session("alice", "ssh"), Session("bob", "vscode")),
        gpu_processes=(GpuProcess(12, "root", container_owner="alice"),),
    )
    board = merge(
        [
            VmInventory(111, "gpu111", "node-a", True),
            VmInventory(112, "off", "node-a", False),
            VmInventory(113, "missing", "node-b", True),
        ],
        {111: snapshot, 113: RuntimeError("no address")},
        NOW,
    )
    store = BoardStore(30)
    store.set_board(board)
    monkeypatch.setattr(web, "now", lambda: NOW)
    return status_response(store)[1]


def test_table_shows_claim_activity_and_errors(payload):
    output = status.render_board(status.parse_board(payload), verbose=True)
    for expected in (
        "Board: FRESH",
        "CLAIMED",
        "alice",
        "proj",
        "2026-11-04T13:00:00+01:00",
        "sessions: alice, bob",
        "GPU users: alice",
        "N/A",
        "UNAVAILABLE",
        "error: no address",
        "claim message: hello  [31mworld",
    ):
        assert expected in output
    assert "\x1b" not in output


def test_compact_table_shows_every_vm_in_at_most_80_columns(payload):
    output = status.render_board(status.parse_board(payload))
    lines = output.splitlines()
    assert len(lines) == 5
    assert all(len(line) <= 80 for line in lines)
    assert "CLAIMED" in lines[2] and "alice,bob" in lines[2]
    assert "OFF" in lines[3] and "N/A" in lines[3]
    assert "UNREACHABLE" in lines[4] and "UNAVAILABLE" in lines[4]
    assert "error:" not in output
    assert "observed:" not in output


def test_colors_and_no_color_have_same_visible_content(payload):
    board = status.parse_board(payload)
    plain = status.render_board(board)
    colored = status.render_board(board, color=True)
    assert "\x1b[36m" in colored
    assert "\x1b[31m" in colored
    assert re.sub(r"\x1b\[[0-9]+m", "", colored) == plain


def test_unicode_columns_and_long_names(payload):
    payload["vms"][0]["inventory"]["name"] = "世界longname-123456"
    board = status.parse_board(payload)
    output = status.render_board(board)
    assert "世界longname-~" in output
    assert "世界longname-123456" in status.render_board(board, verbose=True)


@pytest.mark.parametrize(
    ("tty", "term", "no_color", "option", "colored"),
    [
        (True, "xterm", None, [], True),
        (False, "xterm", None, [], False),
        (True, "dumb", None, [], False),
        (True, "xterm", "1", [], False),
        (False, "dumb", "1", ["--color", "always"], True),
        (True, "xterm", None, ["--color", "never"], False),
    ],
)
def test_color_modes(
    payload, monkeypatch, capsys, tmp_path, tty, term, no_color, option, colored
):
    config = tmp_path / "agent.yaml"
    config.write_text("{}\n")

    def fetch(url):
        assert url == "http://host/status.json"
        return status.parse_board(payload), payload

    monkeypatch.setattr(status, "fetch_status", fetch)
    monkeypatch.setattr(status.sys.stdout, "isatty", lambda: tty)
    monkeypatch.setenv("TERM", term)
    if no_color is None:
        monkeypatch.delenv("NO_COLOR", raising=False)
    else:
        monkeypatch.setenv("NO_COLOR", no_color)
    assert (
        status.main(
            ["--config", str(config), "--url", "http://host/status.json", *option]
        )
        == 0
    )
    assert ("\x1b[" in capsys.readouterr().out) is colored


def test_stale_board_and_snapshot_warning_visible(payload):
    payload["freshness"] = "STALE"
    payload["vms"][0]["snapshot_freshness"] = "CLOCK_WARNING"
    output = status.render_board(status.parse_board(payload))
    assert "WARNING: board inventory and statuses may not be current." in output
    assert "CLOCK_WARNING" in output
    assert "CLAIMED" in output


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("generated_at", None),
        ("generated_at", "2026-01-01T00:00:00"),
        ("freshness", "BAD"),
        ("assessed_at", None),
        ("vms", None),
    ],
)
def test_invalid_board_fields_fail(payload, field, value):
    payload[field] = value
    with pytest.raises(ValueError):
        status.parse_board(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "BAD"),
        ("snapshot_freshness", "FRESH"),
        ("snapshot", {}),
        ("error", 42),
    ],
)
def test_invalid_vm_fields_fail(payload, field, value):
    payload["vms"][2][field] = value
    with pytest.raises(ValueError):
        status.parse_board(payload)


def test_duplicate_vm_id_rejected(payload):
    payload["vms"].append(deepcopy(payload["vms"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        status.parse_board(payload)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ftp://example.com",
        "http://user:pass@example.com",
        "http://host:99999",
        "http://host:0",
        "http://host/path?secret=1",
        "http://host/#x",
        "http://bad host",
    ],
)
def test_invalid_url_rejected(url):
    with pytest.raises(ValueError):
        validate_collector_status_url(url)


def test_config_url_is_optional_and_validated(tmp_path: Path):
    config = tmp_path / "agent.yaml"
    config.write_text("collector_status_url: http://10.0.0.123:8080/status.json\n")
    assert load_agent_config(config).collector_status_url == (
        "http://10.0.0.123:8080/status.json"
    )
    config.write_text("collector_status_url: null\n")
    with pytest.raises(ValueError, match="collector_status_url"):
        load_agent_config(config)


def test_client_against_real_endpoint(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(web, "now", lambda: NOW)
    server_store = BoardStore(30)
    server = make_server("127.0.0.1", 0, server_store)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/status.json"
    config = tmp_path / "agent.yaml"
    config.write_text(f"collector_status_url: {url}\n")
    try:
        assert status.main(["--config", str(config)]) == 1
        assert "HTTP 503" in capsys.readouterr().err
        server_store.set_board(
            merge(
                [VmInventory(111, "gpu111", "node", True)], {111: make_snapshot()}, NOW
            )
        )
        assert status.main(["--config", str(config)]) == 0
        assert "gpu111" in capsys.readouterr().out
        assert status.main(["--config", str(config), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["vms"][0]["inventory"]["vmid"] == 111
        assert data["freshness"] == "FRESH"
        assert status.main(["--config", str(config), "--color", "always"]) == 0
        assert "\x1b[32m" in capsys.readouterr().out
        assert (
            status.main(["--config", str(config), "--json", "--color", "always"]) == 0
        )
        assert "\x1b" not in capsys.readouterr().out
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_connection_and_invalid_json_fail(monkeypatch, capsys, tmp_path):
    config = tmp_path / "agent.yaml"
    config.write_text("{}\n")
    monkeypatch.setattr(status, "urlopen", Mock(side_effect=URLError("timeout")))
    assert (
        status.main(["--config", str(config), "--url", "http://host/status.json"]) == 1
    )
    assert "timeout" in capsys.readouterr().err
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b"not json"
    monkeypatch.setattr(status, "urlopen", Mock(return_value=response))
    assert (
        status.main(["--config", str(config), "--url", "http://host/status.json"]) == 1
    )
    assert "invalid JSON" in capsys.readouterr().err
    response.read.return_value = b"x" * (status.MAX_RESPONSE_BYTES + 1)
    assert (
        status.main(["--config", str(config), "--url", "http://host/status.json"]) == 1
    )
    assert "size limit" in capsys.readouterr().err


def test_missing_url_is_explicit(tmp_path, capsys):
    config = tmp_path / "agent.yaml"
    config.write_text("{}\n")
    assert status.main(["--config", str(config)]) == 1
    assert "collector_status_url" in capsys.readouterr().err
