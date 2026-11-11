import json
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from gpuboard_collector import main
from gpuboard_collector.config import CollectorConfig
from gpuboard_common.models import VmInventory, VmStatus
from tests.conftest import NOW, make_snapshot


def test_one_cycle_writes_mixed_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "collector.yaml"
    status_path = tmp_path / "status.json"
    config = CollectorConfig(status_path=status_path)
    running = VmInventory(111, "gpu", "pve-a", True, address="vm111")
    stopped = VmInventory(112, "off", "pve-a", False)
    missing = VmInventory(113, "unreachable", "pve-b", True)
    inventory = [running, stopped, missing]
    snapshot = make_snapshot()
    load = Mock(return_value=config)
    fetch = Mock(return_value=inventory)
    pull = Mock(return_value={111: snapshot, 113: ValueError("missing address")})
    clock = Mock(return_value=NOW)
    monkeypatch.setattr(main, "load_collector_config", load)
    monkeypatch.setattr(main, "fetch_inventory", fetch)
    monkeypatch.setattr(main, "pull_all", pull)
    monkeypatch.setattr(main, "now", clock)

    board = main.poll_once(str(config_path))

    load.assert_called_once_with(config_path)
    fetch.assert_called_once_with(config)
    pull.assert_called_once_with(config, inventory)
    clock.assert_called_once_with()
    assert [entry.status for entry in board.vms] == [
        VmStatus.FREE,
        VmStatus.OFF_UNREACHABLE,
        VmStatus.OFF_UNREACHABLE,
    ]
    assert board.vms[0].snapshot == snapshot
    data = json.loads(status_path.read_text(encoding="utf-8"))
    assert data["generated_at"] == NOW.isoformat()
    assert data["vms"][0]["snapshot"]["hostname"] == snapshot.hostname
    assert data["vms"][1]["error"] is None
    assert data["vms"][2]["error"] == "missing address"


def test_default_config_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = CollectorConfig(status_path=tmp_path / "status.json")
    load = Mock(return_value=config)
    monkeypatch.setattr(main, "load_collector_config", load)
    monkeypatch.setattr(main, "fetch_inventory", Mock(return_value=[]))
    monkeypatch.setattr(main, "pull_all", Mock(return_value={}))
    monkeypatch.setattr(main, "now", Mock(return_value=NOW))
    main.poll_once()
    load.assert_called_once_with(None)


@pytest.mark.parametrize(
    "stage", ["load_collector_config", "fetch_inventory", "pull_all"]
)
def test_failed_cycle_preserves_previous_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    status_path = tmp_path / "status.json"
    status_path.write_text("previous", encoding="utf-8")
    config = CollectorConfig(status_path=status_path)
    load = Mock(return_value=config)
    fetch = Mock(return_value=[])
    pull = Mock(return_value={})
    mocks = {"load_collector_config": load, "fetch_inventory": fetch, "pull_all": pull}
    for name, mock in mocks.items():
        monkeypatch.setattr(main, name, mock)
    mocks[stage].side_effect = RuntimeError(f"{stage} failed")
    with pytest.raises(RuntimeError, match="failed"):
        main.poll_once()
    assert status_path.read_text(encoding="utf-8") == "previous"
    if stage == "load_collector_config":
        fetch.assert_not_called()
        pull.assert_not_called()
    elif stage == "fetch_inventory":
        pull.assert_not_called()


def test_write_failure_is_not_reported_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = CollectorConfig(status_path=tmp_path / "status.json")
    monkeypatch.setattr(main, "load_collector_config", Mock(return_value=config))
    monkeypatch.setattr(main, "fetch_inventory", Mock(return_value=[]))
    monkeypatch.setattr(main, "pull_all", Mock(return_value={}))
    monkeypatch.setattr(main, "now", Mock(return_value=NOW))
    write = Mock(side_effect=OSError("disk full"))
    monkeypatch.setattr(main, "write_status", write)
    with pytest.raises(OSError, match="disk full"):
        main.poll_once()
    assert write.call_args == call(main.merge([], {}, NOW), config.status_path)
