"""Logged-in session detection."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import UTC, datetime

from gpuboard_agent.users import username_for_uid
from gpuboard_common.models import Session, SessionKind

_SESSION_ID = re.compile(r"[A-Za-z0-9]+")
_PROPERTIES = ("Name", "Class", "Service", "Remote", "RemoteHost", "TTY", "Timestamp")
_TIMESTAMP = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) " r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC"
)
_VSCODE_SERVER_PATH = re.compile(r"(?:^|/)\.vscode-server(?:-insiders)?/")
_SCRIPT_INTERPRETERS = frozenset({"sh", "bash", "node", "nodejs"})


def list_login_sessions() -> list[Session]:
    """Return user sessions from logind; propagate command and parsing failures.

    Session details can disappear between the two commands. In that case the
    failing command is reported rather than silently returning incomplete data.
    """
    result = subprocess.run(
        ["loginctl", "list-sessions", "--no-legend", "--no-pager"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    sessions: list[Session] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        columns = line.split()
        if len(columns) < 3 or not _SESSION_ID.fullmatch(columns[0]):
            raise ValueError(f"invalid loginctl session row: {line!r}")
        details = subprocess.run(
            [
                "loginctl",
                "show-session",
                columns[0],
                "--no-pager",
                "--all",
                *(f"--property={name}" for name in _PROPERTIES),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
        )
        sessions.extend(parse_loginctl_output(details.stdout))
    return sessions


def parse_loginctl_output(text: str) -> list[Session]:
    """Parse one ``loginctl show-session`` property listing.

    Greeter and other non-user session classes are excluded. Remote sessions
    not identified as SSH by their PAM service are labeled ``remote``.
    """
    properties: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in properties:
            raise ValueError(f"invalid loginctl property: {line!r}")
        properties[key] = value
    missing = set(_PROPERTIES) - properties.keys()
    if missing:
        raise ValueError(f"missing loginctl properties: {', '.join(sorted(missing))}")
    if not properties["Class"].startswith("user"):
        return []
    if not properties["Name"]:
        raise ValueError("loginctl session has no user name")
    remote = properties["Remote"]
    if remote not in {"yes", "no"}:
        raise ValueError(f"invalid loginctl Remote value: {remote!r}")
    service = properties["Service"]
    kind: SessionKind = (
        "ssh"
        if service == "sshd" or service.startswith("sshd-")
        else "remote" if remote == "yes" else "local"
    )
    timestamp = properties["Timestamp"]
    since = None
    if timestamp and timestamp != "n/a":
        match = _TIMESTAMP.fullmatch(timestamp)
        if match is None:
            raise ValueError(f"invalid loginctl Timestamp: {timestamp!r}")
        since = datetime.fromisoformat(match.group(1)).replace(tzinfo=UTC)
    return [
        Session(
            user=properties["Name"],
            kind=kind,
            tty=properties["TTY"] or None,
            remote_host=properties["RemoteHost"] or None,
            since=since,
        )
    ]


def find_vscode_users() -> set[str]:
    """Return users with VS Code server processes, not confirmed connections.

    Inspect executable paths and scripts run by common interpreters. Processes
    can linger after a client disconnects. Visibility depends on procfs access.
    """
    result = subprocess.run(
        ["ps", "-eo", "euid=,args=", "-ww"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    uids: set[int] = set()
    for line in result.stdout.splitlines():
        columns = line.split(maxsplit=1)
        if len(columns) != 2 or not columns[0].isdigit():
            raise ValueError(f"invalid ps process row: {line!r}")
        args = columns[1].split()
        if not args:
            raise ValueError(f"missing ps process command: {line!r}")
        executable = args[0]
        is_server = bool(_VSCODE_SERVER_PATH.search(executable))
        if not is_server and os.path.basename(executable) in _SCRIPT_INTERPRETERS:
            is_server = len(args) > 1 and bool(_VSCODE_SERVER_PATH.search(args[1]))
        if is_server:
            uids.add(int(columns[0]))
    return {username_for_uid(uid) for uid in uids}


def merge_vscode_sessions(
    sessions: list[Session], vscode_users: set[str]
) -> list[Session]:
    """Append one VS Code process signal per user without changing logins.

    A server process is not proof of an active connection and cannot be
    attributed to a particular login session.
    """
    existing = {session.user for session in sessions if session.kind == "vscode"}
    return [
        *sessions,
        *(
            Session(user=user, kind="vscode")
            for user in sorted(vscode_users - existing)
        ),
    ]


def exclude_session_users(
    sessions: list[Session], excluded_users: tuple[str, ...]
) -> list[Session]:
    """Exclude configured service accounts from observed session signals."""
    excluded = set(excluded_users)
    return [session for session in sessions if session.user not in excluded]
