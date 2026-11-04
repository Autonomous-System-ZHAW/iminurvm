from datetime import timedelta

import pytest

from gpuboard_common.models import Container, GpuProcess, Session, VmStatus
from gpuboard_common.status import derive_status
from tests.conftest import NOW, make_claim, make_snapshot

ALICE = Session(user="alice")
BOB = Session(user="bob")
EXPIRED = {"start": timedelta(hours=-5), "end": timedelta(hours=-1)}


def test_free() -> None:
    assert derive_status(make_snapshot(), NOW) is VmStatus.FREE


def test_stopped_vm_is_off() -> None:
    snap = make_snapshot(sessions=(ALICE,), vm_running=False)
    assert derive_status(snap, NOW) is VmStatus.OFF_UNREACHABLE


def test_unreachable_agent() -> None:
    assert (
        derive_status(make_snapshot(reachable=False), NOW) is VmStatus.OFF_UNREACHABLE
    )


def test_claimed_without_usage() -> None:
    assert derive_status(make_snapshot(make_claim()), NOW) is VmStatus.CLAIMED


def test_claimed_with_owner_usage() -> None:
    snap = make_snapshot(make_claim(), (ALICE,), (GpuProcess(pid=1, user="alice"),))
    assert derive_status(snap, NOW) is VmStatus.CLAIMED


def test_foreign_session_alone_is_not_conflict() -> None:
    snap = make_snapshot(make_claim(), (ALICE, BOB))
    assert derive_status(snap, NOW) is VmStatus.CLAIMED


def test_foreign_gpu_process_is_conflict() -> None:
    snap = make_snapshot(make_claim(), gpu_processes=(GpuProcess(pid=2, user="bob"),))
    assert derive_status(snap, NOW) is VmStatus.CONFLICT


def test_container_owner_label_wins_over_root() -> None:
    own = GpuProcess(pid=3, user="root", container="c", container_owner="alice")
    assert derive_status(make_snapshot(make_claim(), gpu_processes=(own,)), NOW) is (
        VmStatus.CLAIMED
    )
    foreign = GpuProcess(pid=3, user="root", container="c", container_owner="bob")
    assert derive_status(
        make_snapshot(make_claim(), gpu_processes=(foreign,)), NOW
    ) is (VmStatus.CONFLICT)


def test_unlabeled_root_container_conflicts() -> None:
    snap = make_snapshot(make_claim(), gpu_processes=(GpuProcess(pid=4, user="root"),))
    assert derive_status(snap, NOW) is VmStatus.CONFLICT


def test_unclaimed_usage_session() -> None:
    assert (
        derive_status(make_snapshot(sessions=(BOB,)), NOW) is VmStatus.UNCLAIMED_USAGE
    )


def test_unclaimed_usage_gpu() -> None:
    snap = make_snapshot(gpu_processes=(GpuProcess(pid=5, user="bob"),))
    assert derive_status(snap, NOW) is VmStatus.UNCLAIMED_USAGE


def test_expired_owner_still_logged_in() -> None:
    snap = make_snapshot(make_claim(**EXPIRED), (ALICE,))
    assert derive_status(snap, NOW) is VmStatus.CLAIM_EXPIRED


def test_expired_owner_gpu_process() -> None:
    snap = make_snapshot(
        make_claim(**EXPIRED), gpu_processes=(GpuProcess(pid=6, user="alice"),)
    )
    assert derive_status(snap, NOW) is VmStatus.CLAIM_EXPIRED


def test_expired_only_others_active() -> None:
    snap = make_snapshot(make_claim(**EXPIRED), (BOB,))
    assert derive_status(snap, NOW) is VmStatus.UNCLAIMED_USAGE


def test_expired_and_idle_is_free() -> None:
    assert derive_status(make_snapshot(make_claim(**EXPIRED)), NOW) is VmStatus.FREE


def test_claim_expires_exactly_at_end() -> None:
    claim = make_claim(end=timedelta(0))
    assert derive_status(make_snapshot(claim, (ALICE,)), NOW) is VmStatus.CLAIM_EXPIRED


def test_planned_claim_is_ignored_for_status() -> None:
    planned = make_claim(start=timedelta(hours=2), end=timedelta(hours=4))
    assert derive_status(make_snapshot(planned), NOW) is VmStatus.FREE
    assert derive_status(make_snapshot(planned, (BOB,)), NOW) is (
        VmStatus.UNCLAIMED_USAGE
    )


def test_off_wins_over_claim() -> None:
    snap = make_snapshot(make_claim(), vm_running=False)
    assert derive_status(snap, NOW) is VmStatus.OFF_UNREACHABLE


def test_container_labels() -> None:
    c = Container(id="x", name="n", labels={"owner": "alice", "project": "p"})
    assert (c.owner, c.project) == ("alice", "p")
    assert Container(id="x", name="n").owner is None


@pytest.mark.parametrize("hours", [0, 1, 24])
def test_status_is_pure(hours: int) -> None:
    snap = make_snapshot(make_claim())
    now = NOW + timedelta(hours=hours)
    assert derive_status(snap, now) is derive_status(snap, now)
