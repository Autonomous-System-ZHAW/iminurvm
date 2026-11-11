import json
from pathlib import Path
from unittest.mock import Mock, call

import pytest
from proxmoxer.core import ResourceException

from gpuboard_collector import main
from gpuboard_collector.config import CollectorConfig
from gpuboard_collector.web import BoardStore
from gpuboard_common.models import BoardState, VmInventory
from tests.conftest import NOW, make_snapshot


def test_loop_retries_failed_cycle_and_preserves_old_status_until_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    target = tmp_path / "status.json"
    target.write_text("previous", encoding="utf-8")
    config = CollectorConfig(status_path=target, poll_interval_seconds=2)
    vm = VmInventory(111, "vm", "node", True)
    fetch = Mock(side_effect=[ResourceException(500, "down", "error"), [vm]])
    monkeypatch.setattr(main, "fetch_inventory", fetch)
    monkeypatch.setattr(main, "pull_all", Mock(return_value={111: make_snapshot()}))
    monkeypatch.setattr(main, "load_collector_config", Mock(return_value=config))
    monkeypatch.setattr(main, "now", Mock(return_value=NOW))

    def wait(seconds: float) -> None:
        assert seconds == 2
        if fetch.call_count == 1:
            assert target.read_text(encoding="utf-8") == "previous"
        else:
            raise KeyboardInterrupt

    monkeypatch.setattr(main.time, "sleep", wait)
    with pytest.raises(KeyboardInterrupt):
        main.poll_forever(config)
    assert json.loads(target.read_text(encoding="utf-8"))["generated_at"] == (
        NOW.isoformat()
    )
    assert "Collector cycle failed" in caplog.text
    assert fetch.call_count == 2


def test_config_reload_failure_skips_poll_until_fixed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    config = CollectorConfig(poll_interval_seconds=2)
    updated = CollectorConfig(poll_interval_seconds=5)
    board = BoardState(NOW)
    poll = Mock(return_value=board)
    reload = Mock(side_effect=[ValueError("broken config"), updated])
    sleep = Mock(side_effect=[None, None, KeyboardInterrupt()])
    monkeypatch.setattr(main, "_poll", poll)
    monkeypatch.setattr(main, "load_collector_config", reload)
    monkeypatch.setattr(main.time, "sleep", sleep)

    with pytest.raises(KeyboardInterrupt):
        main.poll_forever(config, Path("/test/config.yaml"))
    assert poll.call_args_list == [call(config), call(updated)]
    assert sleep.call_args_list == [call(2), call(2), call(5)]
    assert "configuration reload failed" in caplog.text


def test_per_vm_error_is_logged(monkeypatch, caplog) -> None:
    from gpuboard_collector.merge import merge

    vm = VmInventory(111, "vm", "node", True)
    board = merge([vm], {111: RuntimeError("no address")}, NOW)
    monkeypatch.setattr(main, "_poll", Mock(return_value=board))
    monkeypatch.setattr(main.time, "sleep", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        main.poll_forever(CollectorConfig())
    assert "VM 111: no address" in caplog.text


def test_main_invalid_initial_config_exits(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        main, "load_collector_config", Mock(side_effect=ValueError("bad config"))
    )
    loop = Mock()
    monkeypatch.setattr(main, "poll_forever", loop)
    assert main.main(["--config", "/test/collector.yaml"]) == 1
    assert "bad config" in caplog.text
    loop.assert_not_called()


def test_main_ctrl_c_is_clean(monkeypatch) -> None:
    config = CollectorConfig()
    load = Mock(return_value=config)
    loop = Mock(side_effect=KeyboardInterrupt)
    server = Mock()
    monkeypatch.setattr(main, "load_collector_config", load)
    monkeypatch.setattr(main, "poll_forever", loop)
    monkeypatch.setattr(main, "make_server", Mock(return_value=server))
    server.server_address = ("127.0.0.1", 8080)
    assert main.main(["--config", "/test/collector.yaml"]) == 0
    load.assert_called_once_with(Path("/test/collector.yaml"))
    assert loop.call_args.args[:2] == (config, Path("/test/collector.yaml"))
    assert isinstance(loop.call_args.args[2], BoardStore)
    server.shutdown.assert_called_once()
    server.server_close.assert_called_once()


def test_main_listener_failure_exits(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        main, "load_collector_config", Mock(return_value=CollectorConfig())
    )
    monkeypatch.setattr(
        main, "make_server", Mock(side_effect=OSError("address in use"))
    )
    loop = Mock()
    monkeypatch.setattr(main, "poll_forever", loop)
    assert main.main([]) == 1
    assert "address in use" in caplog.text
    loop.assert_not_called()


def test_loop_publishes_success_and_updates_interval_on_reload(monkeypatch) -> None:
    config = CollectorConfig(poll_interval_seconds=2)
    updated = CollectorConfig(poll_interval_seconds=5)
    board = BoardState(NOW)
    store = BoardStore(2)
    monkeypatch.setattr(main, "_poll", Mock(side_effect=[board, OSError("down")]))
    monkeypatch.setattr(main, "load_collector_config", Mock(return_value=updated))

    def wait(seconds: float) -> None:
        assert store.read() == (board, seconds)
        if seconds == 5:
            raise KeyboardInterrupt

    monkeypatch.setattr(main.time, "sleep", wait)
    with pytest.raises(KeyboardInterrupt):
        main.poll_forever(config, store=store)
    assert store.read() == (board, 5)


def test_unexpected_error_is_not_swallowed(monkeypatch) -> None:
    monkeypatch.setattr(main, "_poll", Mock(side_effect=AssertionError("bug")))
    with pytest.raises(AssertionError, match="bug"):
        main.poll_forever(CollectorConfig())
