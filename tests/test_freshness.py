from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from gpuboard_collector.freshness import Freshness, assess_board, assess_timestamp
from gpuboard_collector.merge import merge
from gpuboard_common.models import VmInventory, VmStatus
from tests.conftest import NOW, make_snapshot


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=-91), Freshness.STALE),
        (timedelta(seconds=-90, microseconds=-1), Freshness.STALE),
        (timedelta(seconds=-90), Freshness.FRESH),
        (timedelta(0), Freshness.FRESH),
        (timedelta(seconds=30), Freshness.FRESH),
        (timedelta(seconds=30, microseconds=1), Freshness.CLOCK_WARNING),
    ],
)
def test_freshness_exact_boundaries(delta: timedelta, expected: Freshness) -> None:
    assert assess_timestamp(NOW + delta, NOW, 30) is expected


def test_custom_poll_interval() -> None:
    assert assess_timestamp(NOW - timedelta(seconds=31), NOW, 10) is Freshness.STALE
    assert assess_timestamp(NOW - timedelta(seconds=31), NOW, 20) is Freshness.FRESH


def test_daylight_saving_transition_uses_elapsed_time() -> None:
    zone = ZoneInfo("Europe/Zurich")
    before = datetime(2026, 10, 25, 2, 59, tzinfo=zone, fold=0)
    after = datetime(2026, 10, 25, 2, 0, tzinfo=zone, fold=1)
    assert assess_timestamp(before, after, 30) is Freshness.FRESH


@pytest.mark.parametrize("interval", [0, -1, float("inf"), float("nan"), True])
def test_invalid_interval(interval: float) -> None:
    with pytest.raises(ValueError, match="interval"):
        assess_timestamp(NOW, NOW, interval)
    with pytest.raises(ValueError, match="interval"):
        assess_board(None, NOW, interval)


def test_naive_timestamps_rejected() -> None:
    naive = datetime(2026, 1, 1)
    with pytest.raises(ValueError, match="offset"):
        assess_timestamp(naive, NOW, 30)
    with pytest.raises(ValueError, match="offset"):
        assess_timestamp(NOW, naive, 30)
    with pytest.raises(ValueError, match="offset"):
        assess_board(None, naive, 30)


def test_board_and_snapshots_have_independent_freshness() -> None:
    vms = [
        VmInventory(1, "old", "node", True),
        VmInventory(2, "future", "node", True),
        VmInventory(3, "missing", "node", True),
        VmInventory(4, "off", "node", False),
        VmInventory(5, "fresh", "node", True),
    ]
    results = {
        1: replace(make_snapshot(), collected_at=NOW - timedelta(seconds=91)),
        2: replace(make_snapshot(), collected_at=NOW + timedelta(seconds=31)),
        5: make_snapshot(),
    }
    board = merge(vms, results, NOW)
    assessment = assess_board(board, NOW, 30)
    assert assessment.board is Freshness.FRESH
    assert assessment.snapshots == {
        1: Freshness.STALE,
        2: Freshness.CLOCK_WARNING,
        3: Freshness.UNAVAILABLE,
        4: Freshness.NOT_APPLICABLE,
        5: Freshness.FRESH,
    }
    assert board.vms[0].status is VmStatus.FREE
    assert assess_board(board, NOW + timedelta(seconds=91), 30).board is Freshness.STALE
    assert assess_board(board, NOW - timedelta(seconds=31), 30).board is (
        Freshness.CLOCK_WARNING
    )


def test_absent_board() -> None:
    result = assess_board(None, NOW, 30)
    assert result.board is Freshness.UNAVAILABLE
    assert result.snapshots == {}
