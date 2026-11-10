import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from gpuboard_common.claimfile import (
    ClaimError,
    claim_from_dict,
    claim_to_dict,
    delete_claim,
    is_active,
    is_cleanup_due,
    is_expired,
    is_planned,
    load_claim,
    remaining,
    save_claim,
)
from gpuboard_common.timeutil import parse_iso
from tests.conftest import NOW, make_claim


def test_load_valid_manual(fixtures_dir: Path) -> None:
    claim = load_claim(fixtures_dir / "claims" / "valid_manual.json")
    assert claim is not None
    assert (claim.owner, claim.kind, claim.pid) == ("alice", "manual", None)
    assert claim.end - claim.start == timedelta(hours=4)


def test_load_valid_run(fixtures_dir: Path) -> None:
    claim = load_claim(fixtures_dir / "claims" / "valid_run.json")
    assert claim is not None and claim.pid == 31337


def test_load_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_claim(tmp_path / "nope.json") is None


@pytest.mark.parametrize("name", ["invalid_naive_time", "invalid_end_before_start"])
def test_load_invalid(fixtures_dir: Path, name: str) -> None:
    with pytest.raises(ClaimError):
        load_claim(fixtures_dir / "claims" / f"{name}.json")


def test_load_garbage(tmp_path: Path) -> None:
    path = tmp_path / "claim.json"
    path.write_text("{not json")
    with pytest.raises(ClaimError):
        load_claim(path)
    path.write_text("[]")
    with pytest.raises(ClaimError):
        load_claim(path)


def test_missing_fields() -> None:
    with pytest.raises(ClaimError, match="missing"):
        claim_from_dict({"owner": "alice"})


def test_run_requires_pid() -> None:
    data = claim_to_dict(make_claim(kind="run"))
    data["pid"] = None
    with pytest.raises(ClaimError, match="pid"):
        claim_from_dict(data)


def test_invalid_kind_and_empty_owner() -> None:
    data = claim_to_dict(make_claim())
    with pytest.raises(ClaimError):
        claim_from_dict({**data, "kind": "weird"})
    with pytest.raises(ClaimError):
        claim_from_dict({**data, "owner": " "})


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "claim.json"
    claim = make_claim()
    save_claim(path, claim)
    assert load_claim(path) == claim
    assert json.loads(path.read_text())["end"] == "2026-11-04T13:00:00+01:00"
    assert path.stat().st_mode & 0o777 == 0o664
    assert [p.name for p in tmp_path.iterdir()] == ["claim.json"]


def test_save_rejects_invalid_and_leaves_no_temp(tmp_path: Path) -> None:
    bad = make_claim(start=timedelta(hours=2), end=timedelta(hours=1))
    with pytest.raises(ClaimError):
        save_claim(tmp_path / "claim.json", bad)
    assert list(tmp_path.iterdir()) == []


def test_delete(tmp_path: Path) -> None:
    path = tmp_path / "claim.json"
    save_claim(path, make_claim())
    delete_claim(path)
    delete_claim(path)
    assert not path.exists()


def test_other_offset_equals_same_instant() -> None:
    data = claim_to_dict(make_claim())
    data["end"] = "2026-11-04T12:00:00+00:00"  # 13:00 in Zurich
    assert claim_from_dict(data).end == make_claim().end


def test_active_expired_planned() -> None:
    claim = make_claim(start=timedelta(hours=-1), end=timedelta(hours=1))
    assert is_active(claim, NOW)
    assert not is_expired(claim, NOW) and not is_planned(claim, NOW)
    assert is_planned(claim, claim.start - timedelta(seconds=1))
    assert is_expired(claim, claim.end)
    assert not is_active(claim, claim.end)
    assert is_active(claim, claim.start)


def test_remaining() -> None:
    claim = make_claim(end=timedelta(hours=2))
    assert remaining(claim, NOW) == timedelta(hours=2)
    assert remaining(claim, NOW + timedelta(hours=3)) == timedelta(hours=-1)


def test_claim_helpers_during_clock_change() -> None:
    zone = ZoneInfo("Europe/Zurich")
    start = datetime(2026, 10, 25, 2, 45, tzinfo=zone, fold=0)
    end = datetime(2026, 10, 25, 2, 45, tzinfo=zone, fold=1)
    claim = replace(make_claim(), start=start, end=end)
    halfway = datetime(2026, 10, 25, 2, 15, tzinfo=zone, fold=1)
    assert is_active(claim, halfway)
    assert remaining(claim, halfway) == timedelta(minutes=30)
    assert not is_cleanup_due(claim, halfway, timedelta(0))
    assert is_expired(claim, end)


def test_cleanup_due() -> None:
    claim = make_claim(end=timedelta(minutes=-30))
    grace = timedelta(minutes=30)
    assert is_cleanup_due(claim, NOW, grace)
    assert not is_cleanup_due(claim, NOW - timedelta(seconds=1), grace)


def test_parse_iso_requires_offset() -> None:
    with pytest.raises(ValueError):
        parse_iso("2026-11-04T10:00:00")
    assert parse_iso("2026-11-04T10:00:00Z").utcoffset() == timedelta(0)
