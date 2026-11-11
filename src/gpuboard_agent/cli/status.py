"""``vm-status``: show the collector's view of all GPU VMs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from gpuboard_agent.cli._common import add_config_argument
from gpuboard_agent.config import load_agent_config, validate_collector_status_url
from gpuboard_common.models import VmSnapshot, VmStatus
from gpuboard_common.serialize import BOARD_SCHEMA_VERSION, snapshot_from_dict
from gpuboard_common.timeutil import parse_iso

TIMEOUT_SECONDS = 3
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_BOARD_FRESHNESS = {"FRESH", "STALE", "CLOCK_WARNING"}
_SNAPSHOT_FRESHNESS = _BOARD_FRESHNESS | {"UNAVAILABLE", "NOT_APPLICABLE"}


@dataclass(frozen=True)
class StatusRow:
    """Validated VM fields needed for terminal display."""

    vmid: int
    name: str
    node: str
    status: VmStatus
    freshness: str
    snapshot: VmSnapshot | None
    error: str | None


@dataclass(frozen=True)
class StatusBoard:
    """Collector observation and the rows displayed by the client."""

    generated_at: str
    assessed_at: str
    freshness: str
    rows: tuple[StatusRow, ...]


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a nonempty string")
    return value


def parse_board(data: object) -> StatusBoard:
    """Validate endpoint fields used by the status client."""
    if not isinstance(data, dict):
        raise ValueError("status response must be an object")
    if type(data.get("schema_version")) is not int or data["schema_version"] != (
        BOARD_SCHEMA_VERSION
    ):
        raise ValueError("unsupported status schema_version")
    generated = _text(data.get("generated_at"), "generated_at")
    assessed = _text(data.get("assessed_at"), "assessed_at")
    parse_iso(generated)
    parse_iso(assessed)
    freshness = _text(data.get("freshness"), "freshness")
    if freshness not in _BOARD_FRESHNESS:
        raise ValueError(f"invalid board freshness: {freshness!r}")
    raw_rows = data.get("vms")
    if not isinstance(raw_rows, list):
        raise ValueError("vms must be an array")
    rows = []
    seen: set[int] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict) or not isinstance(raw.get("inventory"), dict):
            raise ValueError("invalid VM entry or inventory")
        inventory = raw["inventory"]
        vmid = inventory.get("vmid")
        if type(vmid) is not int or vmid <= 0 or vmid in seen:
            raise ValueError("invalid or duplicate VM ID")
        seen.add(vmid)
        running = inventory.get("running")
        if not isinstance(running, bool):
            raise ValueError("inventory.running must be a boolean")
        status = VmStatus(_text(raw.get("status"), "status"))
        row_freshness = _text(raw.get("snapshot_freshness"), "snapshot_freshness")
        if row_freshness not in _SNAPSHOT_FRESHNESS:
            raise ValueError(f"invalid snapshot freshness: {row_freshness!r}")
        if "snapshot" not in raw or "error" not in raw:
            raise ValueError("VM entry missing snapshot or error")
        snapshot_data = raw["snapshot"]
        if snapshot_data is not None and not isinstance(snapshot_data, dict):
            raise ValueError("snapshot must be an object or null")
        snapshot = (
            snapshot_from_dict(snapshot_data) if snapshot_data is not None else None
        )
        if not running and (snapshot is not None or row_freshness != "NOT_APPLICABLE"):
            raise ValueError("stopped VM has invalid snapshot freshness")
        if running and (
            (snapshot is None and row_freshness != "UNAVAILABLE")
            or (snapshot is not None and row_freshness not in _BOARD_FRESHNESS)
        ):
            raise ValueError("running VM has invalid snapshot freshness")
        error = raw["error"]
        if error is not None and not isinstance(error, str):
            raise ValueError("VM error must be a string or null")
        rows.append(
            StatusRow(
                vmid=vmid,
                name=_text(inventory.get("name"), "inventory.name"),
                node=_text(inventory.get("node"), "inventory.node"),
                status=status,
                freshness=row_freshness,
                snapshot=snapshot,
                error=error,
            )
        )
    return StatusBoard(generated, assessed, freshness, tuple(rows))


def fetch_status(url: str) -> tuple[StatusBoard, object]:
    """Fetch and validate a bounded collector response."""
    url = validate_collector_status_url(url)
    try:
        with urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if exc.code == 503:
            raise ValueError("collector has no available board yet (HTTP 503)") from exc
        raise ValueError(f"collector returned HTTP {exc.code}") from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise ValueError(f"collector request failed: {exc}") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("collector response exceeds size limit")
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("collector returned invalid JSON") from exc
    return parse_board(data), data


def _safe(value: str) -> str:
    return "".join(" " if unicodedata.category(c).startswith("C") else c for c in value)


def _cell(value: str, width: int) -> str:
    value = _safe(value)

    def char_width(char: str) -> int:
        if unicodedata.combining(char):
            return 0
        return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1

    size = sum(char_width(char) for char in value)
    if size <= width:
        return value + " " * (width - size)
    result = ""
    used = 0
    for char in value:
        char_size = char_width(char)
        if used + char_size > width - 1:
            break
        result += char
        used += char_size
    return result + "~" + " " * (width - used - 1)


def _paint(text: str, color: str, enabled: bool) -> str:
    return f"\033[{color}m{text}\033[0m" if enabled else text


def _status_label(row: StatusRow) -> str:
    if row.status == VmStatus.OFF_UNREACHABLE:
        return "OFF" if row.freshness == "NOT_APPLICABLE" else "UNREACHABLE"
    return row.status.value


def render_board(
    board: StatusBoard, *, verbose: bool = False, color: bool = False
) -> str:
    """Render a compact table; include additional observations when verbose."""
    status_colors = {
        "FREE": "32",
        "CLAIMED": "36",
        "CLAIM_EXPIRED": "33",
        "UNCLAIMED_USAGE": "33",
        "CONFLICT": "31",
        "OFF": "2",
        "UNREACHABLE": "31",
    }
    freshness_colors = {
        "FRESH": "32",
        "STALE": "33",
        "CLOCK_WARNING": "31",
        "UNAVAILABLE": "31",
        "NOT_APPLICABLE": "2",
    }
    lines = [
        f"Board: {_paint(board.freshness, freshness_colors[board.freshness], color)}"
        f" | generated: {parse_iso(board.generated_at).isoformat(timespec='seconds')}",
    ]
    if verbose:
        lines.append(f"Assessed: {_safe(board.assessed_at)}")
    if board.freshness != "FRESH":
        lines.append("WARNING: board inventory and statuses may not be current.")
    lines.append(
        f"{'ID':<5} {'NAME':<14} {'STATUS':<15} {'CLAIM':<10} "
        f"{'USERS':<14} {'SNAPSHOT'}"
    )
    if not board.rows:
        lines.append("(no VMs in collector inventory)")
    for row in board.rows:
        snapshot = row.snapshot
        claim = snapshot.claim if snapshot else None
        users = (
            sorted(
                {session.user for session in snapshot.sessions}
                | {process.effective_owner for process in snapshot.gpu_processes}
            )
            if snapshot
            else []
        )
        label = _status_label(row)
        observation = "N/A" if row.freshness == "NOT_APPLICABLE" else row.freshness
        lines.append(
            f"{row.vmid:<5} {_cell(row.name, 14)} "
            f"{_paint(f'{label:<15}', status_colors[label], color)} "
            f"{_cell(claim.owner if claim else '-', 10)} "
            f"{_cell(','.join(users) or '-', 14)} "
            f"{_paint(observation, freshness_colors[row.freshness], color)}"
        )
        if not verbose:
            continue
        lines.append(f"  name: {_safe(row.name)} | node: {_safe(row.node)}")
        if claim:
            lines.append(
                f"  claim: {_safe(claim.owner)}"
                f" | project: {_safe(claim.project or '-')}"
                f" | until: {claim.end.isoformat(timespec='seconds')}"
            )
        if snapshot:
            session_users = ", ".join(
                sorted({_safe(session.user) for session in snapshot.sessions})
            )
            owners = ", ".join(
                sorted(
                    {
                        _safe(process.effective_owner)
                        for process in snapshot.gpu_processes
                    }
                )
            )
            lines.append(
                f"  observed: {snapshot.collected_at.isoformat(timespec='seconds')} | "
                f"GPU: {_safe(snapshot.gpu_model or '-')} | "
                f"sessions: {session_users or '-'} | GPU users: {owners or '-'}"
            )
            if claim and claim.message:
                lines.append(f"  claim message: {_safe(claim.message)}")
        if row.error:
            lines.append(f"  error: {_safe(row.error)}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(prog="vm-status", description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="print validated collector JSON"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="show VM details")
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="color output (default: auto for terminals)",
    )
    parser.add_argument("--url", help="override collector status URL")
    add_config_argument(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Display collector status, returning nonzero on unavailable data."""
    args = build_parser().parse_args(argv)
    try:
        config = load_agent_config(Path(args.config) if args.config else None)
        url = args.url if args.url is not None else config.collector_status_url
        if url is None:
            raise ValueError("set collector_status_url in agent.yaml or use --url")
        board, data = fetch_status(url)
        use_color = args.color == "always" or (
            args.color == "auto"
            and sys.stdout.isatty()
            and os.environ.get("TERM") != "dumb"
            and not os.environ.get("NO_COLOR")
        )
        print(
            json.dumps(data, ensure_ascii=True)
            if args.json
            else render_board(board, verbose=args.verbose, color=use_color)
        )
    except (OSError, ValueError, OverflowError) as exc:
        print(f"vm-status: {_safe(str(exc))}", file=sys.stderr)
        return 1
    return 0
