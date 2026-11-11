import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from gpuboard_collector import proxmox
from gpuboard_collector.config import CollectorConfig, PveNodeConfig
from gpuboard_common.models import VmInventory


@pytest.fixture
def node(tmp_path: Path) -> PveNodeConfig:
    secret = tmp_path / "secret"
    secret.write_text("test-token\n", encoding="utf-8")
    return PveNodeConfig("pve-a", "pve.example.org", "board@pve!readonly", secret)


def mock_api(
    monkeypatch: pytest.MonkeyPatch,
    rows: object,
    configs: dict[int, object],
) -> Mock:
    qemu = Mock()
    qemu.get.return_value = rows
    qemu.side_effect = lambda vmid: Mock(
        config=Mock(get=Mock(return_value=configs[vmid]))
    )
    api = Mock()
    api.nodes.return_value.qemu = qemu
    factory = Mock(return_value=api)
    monkeypatch.setattr(proxmox, "ProxmoxAPI", factory)
    return factory


def test_fetch_tagged_running_and_stopped_vms(
    node: PveNodeConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = mock_api(
        monkeypatch,
        [
            {"vmid": 111, "name": "simulation", "status": "running"},
            {"vmid": 112, "name": "other", "status": "running"},
            {"vmid": 113, "name": "offline", "status": "stopped"},
            {"vmid": 114, "name": "gpu-like", "status": "running"},
        ],
        {
            111: {
                "tags": "gpu;simulation",
                "hostpci2": "0000:22:00,pcie=1",
                "hostpci0": "0000:11:00,pcie=1,x-vga=1",
            },
            112: {"hostpci0": "0000:33:00,pcie=1,x-vga=1"},
            113: {"tags": "gpu"},
            114: {"tags": "gpu-other"},
        },
    )
    assert proxmox.fetch_node_inventory(node) == [
        VmInventory(
            111,
            "simulation",
            "pve-a",
            True,
            ("0000:11:00,pcie=1,x-vga=1", "0000:22:00,pcie=1"),
        ),
        VmInventory(113, "offline", "pve-a", False),
    ]
    factory.assert_called_once_with(
        "pve.example.org",
        user="board@pve",
        token_name="readonly",
        token_value="test-token",
        verify_ssl=True,
        timeout=10,
    )
    assert factory.return_value.nodes.return_value.qemu.call_count == 4


def test_unnamed_tagged_vm(
    node: PveNodeConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_api(monkeypatch, [{"vmid": 111, "status": "stopped"}], {111: {"tags": "gpu"}})
    assert proxmox.fetch_node_inventory(node)[0].name == "VM 111"


def test_real_proxmoxer_http_request_shape(
    node: PveNodeConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def send(adapter, request, **kwargs):
        calls.append((request, kwargs))
        if request.url.endswith("/nodes/pve-a/qemu"):
            data = [{"vmid": 111, "name": "sim", "status": "running"}]
        elif request.url.endswith("/nodes/pve-a/qemu/111/config"):
            data = {"tags": "gpu", "hostpci0": "0000:11:00,pcie=1,x-vga=1"}
        else:
            raise AssertionError(f"unexpected request: {request.url}")
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"data": data}).encode()
        response.headers["Content-Type"] = "application/json"
        response.url = request.url
        response.request = request
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    assert proxmox.fetch_node_inventory(node) == [
        VmInventory(111, "sim", "pve-a", True, ("0000:11:00,pcie=1,x-vga=1",))
    ]
    assert len(calls) == 2
    for request, options in calls:
        assert request.method == "GET"
        assert (
            request.headers["Authorization"]
            == "PVEAPIToken=board@pve!readonly=test-token"
        )
        assert options["timeout"] == 10
        assert options["verify"] is True


@pytest.mark.parametrize(
    ("rows", "details"),
    [
        ({}, {}),
        ([None], {}),
        ([{"vmid": True}], {}),
        ([{"vmid": 0}], {}),
        ([{"vmid": "111"}], {}),
        ([{"vmid": 111}, {"vmid": 111}], {111: {}}),
        ([{"vmid": 111}], {111: []}),
        ([{"vmid": 111}], {111: {"tags": []}}),
        ([{"vmid": 111, "status": "unknown"}], {111: {"tags": "gpu"}}),
        ([{"vmid": 111, "status": "running"}], {111: {"tags": "gpu", "hostpci0": 1}}),
    ],
)
def test_invalid_api_data_fails(
    node: PveNodeConfig,
    monkeypatch: pytest.MonkeyPatch,
    rows: object,
    details: dict[int, object],
) -> None:
    mock_api(monkeypatch, rows, details)
    with pytest.raises(ValueError):
        proxmox.fetch_node_inventory(node)


def test_invalid_token_fails_without_connecting(
    node: PveNodeConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = Mock()
    monkeypatch.setattr(proxmox, "ProxmoxAPI", factory)
    invalid = PveNodeConfig(node.name, node.host, "not-a-token", node.token_secret_file)
    with pytest.raises(ValueError, match="token ID"):
        proxmox.fetch_node_inventory(invalid)
    node.token_secret_file.write_text(" \n", encoding="utf-8")
    with pytest.raises(ValueError, match="secret file"):
        proxmox.fetch_node_inventory(node)
    factory.assert_not_called()


def test_api_error_propagates(
    node: PveNodeConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = mock_api(monkeypatch, [], {})
    factory.return_value.nodes.return_value.qemu.get.side_effect = TimeoutError(
        "offline"
    )
    with pytest.raises(TimeoutError, match="offline"):
        proxmox.fetch_node_inventory(node)


def test_combine_nodes_and_addresses(
    node: PveNodeConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = PveNodeConfig("pve-b", "b", "u!t", Path("/token"))
    fetch = Mock(
        side_effect=[
            [VmInventory(111, "one", "pve-a", True)],
            [VmInventory(201, "two", "pve-b", False)],
        ]
    )
    monkeypatch.setattr(proxmox, "fetch_node_inventory", fetch)
    config = CollectorConfig(nodes=(node, other), vm_addresses={111: "vm111.example"})
    assert proxmox.fetch_inventory(config) == [
        VmInventory(111, "one", "pve-a", True, address="vm111.example"),
        VmInventory(201, "two", "pve-b", False),
    ]


def test_duplicate_ids_across_nodes_fail(
    node: PveNodeConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = PveNodeConfig("pve-b", "b", "u!t", Path("/token"))
    monkeypatch.setattr(
        proxmox,
        "fetch_node_inventory",
        Mock(
            side_effect=[
                [VmInventory(111, "one", "pve-a", True)],
                [VmInventory(111, "one", "pve-b", True)],
            ]
        ),
    )
    with pytest.raises(ValueError, match="duplicate VM ID"):
        proxmox.fetch_inventory(CollectorConfig(nodes=(node, other)))
