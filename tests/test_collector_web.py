import json
import threading
from dataclasses import replace
from datetime import timedelta
from http.client import HTTPConnection
from unittest.mock import Mock

import pytest

from gpuboard_collector import main, web
from gpuboard_collector.config import CollectorConfig
from gpuboard_collector.merge import merge
from gpuboard_collector.web import BoardStore, make_server
from gpuboard_common.models import VmInventory
from tests.conftest import NOW, make_snapshot


@pytest.fixture
def listener():
    store = BoardStore(30)
    server = make_server("127.0.0.1", 0, store)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield store, server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def request(port, path="/status.json", method="GET"):
    connection = HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        body = response.read()
        return response.status, dict(response.getheaders()), body
    finally:
        connection.close()


def test_unavailable_until_first_success(listener, monkeypatch):
    _, port = listener
    monkeypatch.setattr(web, "now", lambda: NOW)
    status, headers, body = request(port)
    assert status == 503
    assert headers["Cache-Control"] == "no-store"
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(body) == {
        "schema_version": 1,
        "generated_at": None,
        "vms": [],
        "freshness": "UNAVAILABLE",
        "assessed_at": NOW.isoformat(),
        "poll_interval_seconds": 30,
    }


def test_freshness_changes_at_request_time_without_changing_status(
    listener, monkeypatch
):
    store, port = listener
    vms = [
        VmInventory(1, "fresh", "node", True),
        VmInventory(2, "missing", "node", True),
        VmInventory(3, "off", "node", False),
        VmInventory(4, "future", "node", True),
    ]
    board = merge(
        vms,
        {
            1: make_snapshot(),
            4: replace(make_snapshot(), collected_at=NOW + timedelta(seconds=31)),
        },
        NOW,
    )
    store.set_board(board)
    monkeypatch.setattr(web, "now", lambda: NOW)
    status, _, body = request(port)
    data = json.loads(body)
    assert status == 200
    assert data["freshness"] == "FRESH"
    assert [v["snapshot_freshness"] for v in data["vms"]] == [
        "FRESH",
        "UNAVAILABLE",
        "NOT_APPLICABLE",
        "CLOCK_WARNING",
    ]
    assert data["vms"][0]["status"] == "FREE"
    assert data["vms"][1]["error"] == "No snapshot result received"
    monkeypatch.setattr(web, "now", lambda: NOW + timedelta(seconds=91))
    _, _, body = request(port)
    stale = json.loads(body)
    assert stale["freshness"] == "STALE"
    assert stale["vms"][0]["snapshot_freshness"] == "STALE"
    assert stale["vms"][0]["status"] == "FREE"
    store.set_interval(60)
    _, _, body = request(port)
    assert json.loads(body)["freshness"] == "FRESH"


def test_unknown_paths_and_methods_do_not_expose_status(listener):
    store, port = listener
    store.set_board(merge([], {}, NOW))
    assert request(port, "/")[0] == 404
    assert request(port, "/status.json?x=1")[0] == 404
    assert request(port, method="POST")[0] == 501


def test_invalid_observation_returns_error_and_logs(listener, monkeypatch, caplog):
    store, port = listener
    store.set_board(merge([], {}, NOW))
    monkeypatch.setattr(web, "now", lambda: NOW.replace(tzinfo=None))
    status, _, body = request(port)
    assert status == 500
    assert json.loads(body) == {"error": "status error"}
    assert "Failed to render status response" in caplog.text


def test_http_remains_responsive_while_poll_is_running(listener, monkeypatch):
    store, port = listener
    entered = threading.Event()
    release = threading.Event()
    board = merge([], {}, NOW)

    def poll(config):
        assert config.poll_interval_seconds == 30
        entered.set()
        assert release.wait(3)
        return board

    def run_loop():
        try:
            main.poll_forever(CollectorConfig(poll_interval_seconds=30), store=store)
        except KeyboardInterrupt:
            pass

    monkeypatch.setattr(main, "_poll", poll)
    monkeypatch.setattr(main.time, "sleep", Mock(side_effect=KeyboardInterrupt))
    monkeypatch.setattr(web, "now", lambda: NOW)
    thread = threading.Thread(target=run_loop)
    thread.start()
    try:
        assert entered.wait(3)
        assert request(port)[0] == 503
    finally:
        release.set()
        thread.join(timeout=3)
    assert not thread.is_alive()
    status, _, body = request(port)
    assert status == 200
    assert json.loads(body)["freshness"] == "FRESH"
