from datetime import datetime, timedelta

import pytest

from gpuboard_collector.merge import build_entry, merge
from gpuboard_common.models import GpuProcess, Session, VmInventory, VmStatus
from tests.conftest import NOW, make_claim, make_snapshot

RUNNING = VmInventory(111, "vm111", "pve-b", True, address="vm111")
STOPPED = VmInventory(112, "vm112", "pve-a", False)


@pytest.mark.parametrize(
    ("snapshot", "status"),
    [
        (make_snapshot(), VmStatus.FREE),
        (make_snapshot(make_claim()), VmStatus.CLAIMED),
        (
            make_snapshot(make_claim(), gpu_processes=(GpuProcess(1, "bob"),)),
            VmStatus.CONFLICT,
        ),
        (
            make_snapshot(
                make_claim(start=timedelta(hours=-3), end=timedelta(hours=-1)),
                sessions=(Session("alice"),),
            ),
            VmStatus.CLAIM_EXPIRED,
        ),
        (make_snapshot(sessions=(Session("bob"),)), VmStatus.UNCLAIMED_USAGE),
    ],
)
def test_entry_uses_status_rules(snapshot, status) -> None:
    entry = build_entry(RUNNING, snapshot, NOW)
    assert entry.inventory == RUNNING
    assert entry.status is status
    assert entry.snapshot == snapshot
    assert entry.error is None


def test_stopped_vm_ignores_stale_snapshot_and_error() -> None:
    for result in (make_snapshot(make_claim()), RuntimeError("old failure"), None):
        entry = build_entry(STOPPED, result, NOW)
        assert entry.status is VmStatus.OFF_UNREACHABLE
        assert entry.snapshot is None
        assert entry.error is None


@pytest.mark.parametrize("error", [RuntimeError("ssh failed"), TimeoutError()])
def test_failed_pull_preserves_error(error: Exception) -> None:
    entry = build_entry(RUNNING, error, NOW)
    assert entry.status is VmStatus.OFF_UNREACHABLE
    assert entry.snapshot is None
    assert entry.error == (str(error) or type(error).__name__)


def test_missing_result_is_an_explicit_error() -> None:
    entry = build_entry(RUNNING, None, NOW)
    assert entry.status is VmStatus.OFF_UNREACHABLE
    assert entry.error == "No snapshot result received"


def test_merge_sorts_and_retains_observation_time() -> None:
    snapshot = make_snapshot()
    board = merge([RUNNING, STOPPED], {111: snapshot}, NOW)
    assert board.generated_at == NOW
    assert [entry.inventory.vmid for entry in board.vms] == [112, 111]
    assert board.vms[1].snapshot is snapshot
    assert board.vms[1].snapshot.collected_at == snapshot.collected_at


def test_merge_rejects_duplicate_and_unknown_ids() -> None:
    with pytest.raises(ValueError, match="duplicate VM ID"):
        merge([RUNNING, RUNNING], {}, NOW)
    with pytest.raises(ValueError, match="unknown VM IDs"):
        merge([RUNNING], {999: make_snapshot()}, NOW)


def test_merge_requires_aware_time_even_when_empty() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        merge([], {}, datetime(2026, 11, 11))
