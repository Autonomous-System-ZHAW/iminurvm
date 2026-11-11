from pathlib import Path

import pytest

from gpuboard_collector.config import (
    CollectorConfig,
    PveNodeConfig,
    load_collector_config,
)

NODE = """\
proxmox:
  nodes:
    - name: pve-a
      host: pve-a.example.org
      token_id: board@pve!readonly
      token_secret_file: /etc/gpuboard/token
"""


def load_text(tmp_path: Path, text: str) -> CollectorConfig:
    path = tmp_path / "collector.yaml"
    path.write_text(text, encoding="utf-8")
    return load_collector_config(path)


def test_example_config() -> None:
    config = load_collector_config(Path("collector/collector.example.yaml"))
    assert len(config.nodes) == 2
    assert config.nodes[0] == PveNodeConfig(
        name="pve-a",
        host="pve-a.example.org",
        token_id="gpuboard@pve!readonly",
        token_secret_file=Path("/etc/gpuboard/pve-a.token"),
    )
    assert config.vm_addresses == {
        101: "gpu-101.example.org",
        102: "gpu-102.example.org",
        201: "gpu-201.example.org",
        202: "gpu-202.example.org",
    }


def test_defaults_and_quoted_vm_ids(tmp_path: Path) -> None:
    config = load_text(tmp_path, NODE + 'vm_addresses:\n  "101": vm.example.org\n')
    defaults = CollectorConfig()
    assert config.ssh_user == defaults.ssh_user
    assert config.ssh_key == defaults.ssh_key
    assert config.poll_interval_seconds == 30
    assert config.ssh_timeout_seconds == 10
    assert config.listen_port == 8080
    assert config.vm_addresses == {101: "vm.example.org"}


def test_overrides(tmp_path: Path) -> None:
    config = load_text(
        tmp_path,
        NODE + """\
ssh_user: collector
ssh_key: /opt/keys/id
ssh_timeout_seconds: 2.5
agent_command: /opt/gpuboard/bin/vm-agent
poll_interval_seconds: 60
status_path: /tmp/status.json
listen_host: 127.0.0.1
listen_port: 9090
""",
    )
    assert config.ssh_user == "collector"
    assert config.ssh_key == Path("/opt/keys/id")
    assert config.ssh_timeout_seconds == 2.5
    assert config.agent_command == "/opt/gpuboard/bin/vm-agent"
    assert config.poll_interval_seconds == 60
    assert config.status_path == Path("/tmp/status.json")
    assert config.listen_host == "127.0.0.1"
    assert config.listen_port == 9090


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[]",
        "{}",
        "proxmox: {}",
        "proxmox:\n  nodes: []",
        "proxmox:\n  nodes: [null]",
        "proxmox:\n  nodes:\n    - name: a",
        NODE + "unexpected: true\n",
        NODE.replace("  nodes:", "  extra: true\n  nodes:"),
        NODE.replace("      host:", "      extra: true\n      host:"),
        NODE.replace("pve-a.example.org", '""'),
        NODE.replace("/etc/gpuboard/token", "relative"),
        NODE.replace("      token_id:", "      verify_ssl: 'false'\n      token_id:"),
        NODE + "ssh_key: relative\n",
        NODE + "status_path: relative\n",
        NODE + "ssh_user: ''\n",
        NODE + "listen_port: 0\n",
        NODE + "listen_port: 65536\n",
        NODE + "listen_port: true\n",
        NODE + "listen_port: '8080'\n",
        NODE + "ssh_timeout_seconds: .inf\n",
        NODE + "poll_interval_seconds: .nan\n",
        NODE + "poll_interval_seconds: 0\n",
        NODE + "ssh_timeout_seconds: true\n",
        NODE + "vm_addresses: []\n",
        NODE + "vm_addresses:\n  true: host\n",
        NODE + "vm_addresses:\n  0: host\n",
        NODE + "vm_addresses:\n  abc: host\n",
        NODE + "vm_addresses:\n  101: ''\n",
        NODE + "vm_addresses:\n  101: host\n  '101': other\n",
        NODE + "listen_port: 1\nlisten_port: 2\n",
        NODE.replace("      host:", "      name: duplicate\n      host:"),
        "proxmox: [",
    ],
)
def test_invalid_config(tmp_path: Path, text: str) -> None:
    with pytest.raises(ValueError):
        load_text(tmp_path, text)


def test_duplicate_node_name(tmp_path: Path) -> None:
    text = NODE + """\
    - name: pve-a
      host: another.example.org
      token_id: board@pve!readonly
      token_secret_file: /etc/gpuboard/token2
"""
    with pytest.raises(ValueError, match="duplicate Proxmox node"):
        load_text(tmp_path, text)


def test_missing_config_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gpuboard_collector import config

    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError):
        load_collector_config(missing)
    monkeypatch.setattr(config, "DEFAULT_CONFIG_PATH", missing)
    with pytest.raises(FileNotFoundError):
        load_collector_config()


def test_disable_tls_verification_explicitly(tmp_path: Path) -> None:
    config = load_text(
        tmp_path, NODE.replace("      host:", "      verify_ssl: false\n      host:")
    )
    assert config.nodes[0].verify_ssl is False
