import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from gpuboard_agent import docker
from gpuboard_common.models import Container

ID = "3f4a9c1b2d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f9012345678901234ab"
OTHER_ID = "9a8b7c6d5e4f" + "0" * 52


def test_parse_docker_fixture(fixtures_dir: Path) -> None:
    containers = docker.parse_docker_ps_json(
        (fixtures_dir / "docker_ps.jsonl").read_text()
    )
    assert len(containers) == 2
    assert containers[0].id == ID[:12]
    assert containers[0].name == "isaac-sim-alice"
    assert containers[0].owner == "alice"
    assert containers[0].project == "isaac-demo"
    assert containers[1].labels == {}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", {}),
        ("owner=alice,project=demo", {"owner": "alice", "project": "demo"}),
        (
            "empty=,url=https://a.example?a=b",
            {"empty": "", "url": "https://a.example?a=b"},
        ),
    ],
)
def test_parse_labels(raw: str, expected: dict[str, str]) -> None:
    assert docker.parse_labels(raw) == expected


@pytest.mark.parametrize("raw", ["owner", "=alice", "a=1,a=2", "a=1,", "a=x,y"])
def test_invalid_labels(raw: str) -> None:
    with pytest.raises(ValueError):
        docker.parse_labels(raw)


@pytest.mark.parametrize(
    "text",
    ["not json", "[]", "{}", '{"ID":"bad","Names":"n","Image":"i","Status":"Up"}'],
)
def test_invalid_docker_ps(text: str) -> None:
    with pytest.raises(ValueError):
        docker.parse_docker_ps_json(text)


def test_empty_docker_output() -> None:
    assert docker.parse_docker_ps_json("") == []


def test_cgroup_fixture_variants(fixtures_dir: Path) -> None:
    lines = (fixtures_dir / "cgroup_lines.txt").read_text().splitlines()
    assert [
        docker.container_id_from_cgroup(line)
        for line in lines
        if line and not line.startswith("#")
    ] == [ID, ID, ID, None]


def test_cgroup_nested_and_multiple_controllers() -> None:
    text = f"1:cpu:/docker/{ID}/child\n2:memory:/docker/{ID}\n"
    assert docker.container_id_from_cgroup(text) == ID
    assert (
        docker.container_id_from_cgroup(f"0::/user.slice/docker-{ID}.scope/child") == ID
    )


def test_cgroup_does_not_match_other_runtimes() -> None:
    assert (
        docker.container_id_from_cgroup(f"0::/kubepods/cri-containerd-{ID}.scope")
        is None
    )
    assert docker.container_id_from_cgroup(f"0::/user.slice/{ID}") is None
    assert docker.container_id_from_cgroup("") is None


def test_cgroup_invalid_or_conflicting() -> None:
    with pytest.raises(ValueError):
        docker.container_id_from_cgroup("not a cgroup")
    with pytest.raises(ValueError, match="multiple"):
        docker.container_id_from_cgroup(
            f"1:cpu:/docker/{ID}\n2:memory:/docker/{OTHER_ID}"
        )


def test_find_container_id_prefixes() -> None:
    container = Container(id=ID[:12], name="test")
    assert docker.find_container(ID, [container]) == container
    full = Container(id=ID, name="full")
    assert docker.find_container(ID[:12], [full]) == full
    assert docker.find_container(OTHER_ID, [full]) is None


def test_find_container_invalid_and_ambiguous() -> None:
    with pytest.raises(ValueError):
        docker.find_container("", [])
    containers = [
        Container(id=ID, name="a"),
        Container(id=ID[:12] + "1" * 52, name="b"),
    ]
    with pytest.raises(ValueError, match="ambiguous"):
        docker.find_container(ID[:12], containers)


def _ps_row(container_id: str = ID) -> str:
    return json.dumps(
        {
            "ID": container_id,
            "Names": "example",
            "Image": "image",
            "Status": "Up",
            "Labels": "owner=alice,project=comma,value",
        }
    )


def _result(output: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout=output, stderr="")


def test_list_containers_inspects_exact_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    inspected = [
        {
            "Id": ID,
            "Config": {"Labels": {"owner": "alice", "project": "comma,value"}},
            "State": {"Running": True},
        }
    ]
    run = Mock(side_effect=[_result(_ps_row()), _result(json.dumps(inspected))])
    monkeypatch.setattr(docker.subprocess, "run", run)
    result = docker.list_containers()
    assert result == [
        Container(
            ID, "example", "image", "Up", {"owner": "alice", "project": "comma,value"}
        )
    ]
    assert run.call_args_list[0].args[0] == [
        "docker",
        "ps",
        "--no-trunc",
        "--format",
        "json",
    ]
    assert run.call_args_list[1].args[0] == [
        "docker",
        "inspect",
        "--type",
        "container",
        ID,
    ]
    for call in run.call_args_list:
        assert call.kwargs == {
            "capture_output": True,
            "text": True,
            "check": True,
            "timeout": 10,
        }


def test_list_empty_does_not_inspect(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(return_value=_result(""))
    monkeypatch.setattr(docker.subprocess, "run", run)
    assert docker.list_containers() == []
    assert run.call_count == 1


def test_list_multiple_containers_and_null_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspected = [
        {"Id": OTHER_ID, "Config": {"Labels": None}, "State": {"Running": True}},
        {
            "Id": ID,
            "Config": {"Labels": {"owner": "alice"}},
            "State": {"Running": True},
        },
    ]
    run = Mock(
        side_effect=[
            _result(_ps_row() + "\n" + _ps_row(OTHER_ID)),
            _result(json.dumps(inspected)),
        ]
    )
    monkeypatch.setattr(docker.subprocess, "run", run)
    result = docker.list_containers()
    assert [container.id for container in result] == [ID, OTHER_ID]
    assert result[0].owner == "alice"
    assert result[1].labels == {}


def test_list_rejects_duplicate_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(return_value=_result(_ps_row() + "\n" + _ps_row()))
    monkeypatch.setattr(docker.subprocess, "run", run)
    with pytest.raises(ValueError, match="duplicate"):
        docker.list_containers()
    assert run.call_count == 1


@pytest.mark.parametrize(
    "details",
    [
        "invalid JSON",
        "{}",
        "[]",
        json.dumps([{"Id": ID, "Config": {}, "State": {"Running": True}}]),
        json.dumps([{"Id": ID, "Config": {"Labels": {}}, "State": {"Running": False}}]),
        json.dumps(
            [
                {
                    "Id": ID,
                    "Config": {"Labels": {"owner": 42}},
                    "State": {"Running": True},
                }
            ]
        ),
    ],
)
def test_list_rejects_bad_inspection(
    monkeypatch: pytest.MonkeyPatch, details: str
) -> None:
    run = Mock(side_effect=[_result(_ps_row()), _result(details)])
    monkeypatch.setattr(docker.subprocess, "run", run)
    with pytest.raises(ValueError):
        docker.list_containers()


def test_list_propagates_docker_error(monkeypatch: pytest.MonkeyPatch) -> None:
    error = subprocess.CalledProcessError(1, ["docker", "ps"])
    monkeypatch.setattr(docker.subprocess, "run", Mock(side_effect=error))
    with pytest.raises(subprocess.CalledProcessError):
        docker.list_containers()
