import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from gpuboard_collector import merge
from gpuboard_common.models import BoardState, Session, VmInventory
from gpuboard_common.serialize import board_to_dict, snapshot_to_dict
from tests.conftest import NOW, make_claim, make_snapshot


def example_board() -> BoardState:
    running = VmInventory(111, "gpu", "pve-a", True, ("pci",), "10.0.0.111")
    stopped = VmInventory(112, "off", "pve-b", False)
    failed = VmInventory(113, "unreachable", "pve-b", True)
    snapshot = make_snapshot(make_claim(), sessions=(Session("alice"),))
    return merge.merge(
        [failed, stopped, running], {111: snapshot, 113: RuntimeError("offline")}, NOW
    )


def test_board_json_shape_and_snapshot_contract() -> None:
    board = example_board()
    snapshot = board.vms[0].snapshot
    assert snapshot is not None
    data = board_to_dict(board)
    assert data == {
        "schema_version": 1,
        "generated_at": NOW.isoformat(),
        "vms": [
            {
                "inventory": {
                    "vmid": 111,
                    "name": "gpu",
                    "node": "pve-a",
                    "running": True,
                    "hostpci": ["pci"],
                    "address": "10.0.0.111",
                },
                "status": "CLAIMED",
                "snapshot": snapshot_to_dict(snapshot),
                "error": None,
            },
            {
                "inventory": {
                    "vmid": 112,
                    "name": "off",
                    "node": "pve-b",
                    "running": False,
                    "hostpci": [],
                    "address": None,
                },
                "status": "OFF_UNREACHABLE",
                "snapshot": None,
                "error": None,
            },
            {
                "inventory": {
                    "vmid": 113,
                    "name": "unreachable",
                    "node": "pve-b",
                    "running": True,
                    "hostpci": [],
                    "address": None,
                },
                "status": "OFF_UNREACHABLE",
                "snapshot": None,
                "error": "offline",
            },
        ],
    }
    decoded = json.loads(json.dumps(data))
    assert decoded["vms"][0]["inventory"]["hostpci"] == ["pci"]
    assert decoded["vms"][0]["snapshot"]["collected_at"] == NOW.isoformat()


def test_empty_board_and_naive_time() -> None:
    assert board_to_dict(BoardState(NOW)) == {
        "schema_version": 1,
        "generated_at": NOW.isoformat(),
        "vms": [],
    }
    with pytest.raises(ValueError, match="offset"):
        board_to_dict(BoardState(datetime(2026, 11, 11)))


def test_write_and_replace_status(tmp_path: Path) -> None:
    target = tmp_path / "status.json"
    target.write_text("old", encoding="utf-8")
    board = example_board()
    merge.write_status(board, target)
    assert json.loads(target.read_text(encoding="utf-8")) == json.loads(
        json.dumps(board_to_dict(board))
    )
    assert target.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [target]
    merge.write_status(BoardState(NOW), str(target))
    assert json.loads(target.read_text(encoding="utf-8"))["vms"] == []


def test_replace_failure_preserves_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "status.json"
    target.write_text("old", encoding="utf-8")
    monkeypatch.setattr(merge.os, "replace", Mock(side_effect=OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        merge.write_status(example_board(), target)
    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [target]


def test_write_failure_preserves_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "status.json"
    target.write_text("old", encoding="utf-8")

    def fail_write(data, handle, **kwargs):
        handle.write('{"partial":')
        raise OSError("disk full")

    monkeypatch.setattr(merge.json, "dump", fail_write)
    with pytest.raises(OSError, match="disk full"):
        merge.write_status(example_board(), target)
    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [target]


def test_invalid_snapshot_preserves_old_file(tmp_path: Path) -> None:
    target = tmp_path / "status.json"
    target.write_text("old", encoding="utf-8")
    board = example_board()
    snapshot = board.vms[0].snapshot
    assert snapshot is not None
    invalid = replace(snapshot, collected_at=datetime(2026, 1, 1))
    entry = replace(board.vms[0], snapshot=invalid)
    with pytest.raises(ValueError, match="offset"):
        merge.write_status(replace(board, vms=(entry,)), target)
    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [target]


def test_nonexistent_parent_reports_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        merge.write_status(example_board(), tmp_path / "missing" / "status.json")
