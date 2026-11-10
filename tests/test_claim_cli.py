import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from gpuboard_agent.cli import claim, extend, release
from gpuboard_agent.cli._common import add_duration, parse_duration
from gpuboard_agent.config import AgentConfig
from gpuboard_common.claimfile import load_claim, save_claim
from tests.conftest import NOW, make_claim


@pytest.fixture
def claim_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "claim.json"
    config = AgentConfig(claim_path=path)
    for module in (claim, extend, release):
        monkeypatch.setattr(module, "load_agent_config", lambda path: config)
        monkeypatch.setattr(module, "current_user", lambda: "alice")
    monkeypatch.setattr(claim, "now", lambda: NOW)
    monkeypatch.setattr(extend, "now", lambda: NOW)
    return path


@pytest.mark.parametrize(
    ("text", "hours"), [("90m", 1.5), ("4h", 4), ("1d", 24), ("1.5h", 1.5)]
)
def test_duration(text: str, hours: float) -> None:
    assert parse_duration(text) == hours


@pytest.mark.parametrize(
    "text", ["", "0h", "-1h", "4", "1w", "1h30m", " 4h", "nan", "0.001m"]
)
def test_bad_duration(text: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(text)


def test_duration_across_daylight_saving() -> None:
    start = datetime(2026, 3, 29, 1, 30, tzinfo=ZoneInfo("Europe/Zurich"))
    end = add_duration(start, 2)
    assert end.astimezone(UTC) - start.astimezone(UTC) == timedelta(hours=2)
    assert (end.hour, end.utcoffset()) == (4, timedelta(hours=2))


def test_claim_at_fall_clock_change(
    claim_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start = datetime(2026, 10, 25, 2, 45, tzinfo=ZoneInfo("Europe/Zurich"))
    monkeypatch.setattr(claim, "now", lambda: start)
    assert claim.main(["-d", "1h"]) == 0
    saved = load_claim(claim_path)
    assert saved is not None
    assert saved.end.astimezone(UTC) - saved.start.astimezone(UTC) == timedelta(hours=1)


def test_claim_extend_release(claim_path: Path) -> None:
    assert claim.main(["-p", "sim", "-m", "testing", "-d", "90m"]) == 0
    existing = load_claim(claim_path)
    assert existing is not None
    assert (existing.owner, existing.project, existing.message, existing.kind) == (
        "alice",
        "sim",
        "testing",
        "manual",
    )
    assert existing.start == NOW
    assert existing.end == NOW + timedelta(minutes=90)
    assert extend.main(["2h"]) == 0
    extended = load_claim(claim_path)
    assert extended is not None
    assert extended.end == NOW + timedelta(hours=3, minutes=30)
    assert release.main([]) == 0
    assert load_claim(claim_path) is None
    assert os.stat(claim_path.with_name(".claim.json.lock")).st_mode & 0o777 == 0o664


@pytest.mark.parametrize("kind", ["manual", "run"])
@pytest.mark.parametrize("expired", [False, True])
def test_existing_claims_protected(claim_path: Path, kind: str, expired: bool) -> None:
    original = make_claim(
        owner="bob",
        kind=kind,
        start=timedelta(hours=-3),
        end=timedelta(hours=-1) if expired else timedelta(hours=1),
    )
    save_claim(claim_path, original)
    assert claim.main([]) == 1
    assert load_claim(claim_path) == original


def test_auto_claim_can_be_replaced(claim_path: Path) -> None:
    save_claim(claim_path, make_claim(owner="bob", kind="auto"))
    assert claim.main([]) == 0
    new = load_claim(claim_path)
    assert new is not None and (new.owner, new.kind) == ("alice", "manual")


def test_planned_auto_claim_is_not_overwritten(claim_path: Path) -> None:
    original = make_claim(kind="auto", start=timedelta(hours=1), end=timedelta(hours=2))
    save_claim(claim_path, original)
    assert claim.main([]) == 1
    assert load_claim(claim_path) == original


def test_extend_expired_from_now(claim_path: Path) -> None:
    original = make_claim(start=timedelta(hours=-3), end=timedelta(hours=-1))
    save_claim(claim_path, original)
    assert extend.main(["2h"]) == 0
    updated = load_claim(claim_path)
    assert updated is not None
    assert updated.end == NOW + timedelta(hours=2)
    assert updated.start == original.start


def test_foreign_claim_requires_force(claim_path: Path) -> None:
    original = make_claim(owner="bob")
    save_claim(claim_path, original)
    assert extend.main(["1h"]) == 1
    assert release.main([]) == 1
    assert load_claim(claim_path) == original
    assert release.main(["--force"]) == 0
    assert load_claim(claim_path) is None


def test_missing_claim_and_invalid_duration(
    claim_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert extend.main(["1h"]) == 1
    assert release.main([]) == 1
    assert claim.main(["-d", "0h"]) == 1
    assert load_claim(claim_path) is None
    assert "duration" in capsys.readouterr().err


def test_concurrent_claims_do_not_overwrite(claim_path: Path) -> None:
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: claim.main([]), range(2)))
    assert sorted(results) == [0, 1]
    assert load_claim(claim_path) is not None


def test_commands_with_real_config_in_subprocess(tmp_path: Path) -> None:
    path = tmp_path / "claim.json"
    config = tmp_path / "agent.yaml"
    config.write_text(f"claim_path: {path}\ndefault_claim_hours: 2\n")
    for module, args in (
        ("claim", ["--config", str(config), "-p", "sim"]),
        ("extend", ["--config", str(config), "1h"]),
        ("release", ["--config", str(config)]),
    ):
        command = (
            f"from gpuboard_agent.cli.{module} import main; raise SystemExit(main())"
        )
        result = subprocess.run(
            [sys.executable, "-c", command, *args], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        if module == "claim":
            saved = load_claim(path)
            assert saved is not None and saved.project == "sim"
            assert saved.end - saved.start == timedelta(hours=2)
    assert load_claim(path) is None
