import os
import pwd
import subprocess
import sys
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from gpuboard_agent import sessions
from gpuboard_common.models import Session

PROPERTIES = """\
Name=alice
Class=user
Service=sshd
Remote=yes
RemoteHost=host.example
TTY=pts/0
Timestamp=Mon 2026-11-09 06:34:13 UTC
"""


def test_list_login_sessions(monkeypatch):
    command_output = "2 1000 alice seat0 tty2 active no -\n"
    expected = [Session(user="alice", kind="local")]

    run = Mock(
        side_effect=[
            subprocess.CompletedProcess(
                args=["loginctl"], returncode=0, stdout=command_output, stderr=""
            ),
            subprocess.CompletedProcess(
                args=["loginctl"], returncode=0, stdout=PROPERTIES, stderr=""
            ),
        ]
    )
    parse = Mock(return_value=expected)

    monkeypatch.setattr(sessions.subprocess, "run", run)
    monkeypatch.setattr(sessions, "parse_loginctl_output", parse)

    assert sessions.list_login_sessions() == expected
    parse.assert_called_once_with(PROPERTIES)
    assert run.call_args_list[0].args == (
        ["loginctl", "list-sessions", "--no-legend", "--no-pager"],
    )
    assert run.call_args_list[0].kwargs == {
        "capture_output": True,
        "text": True,
        "check": True,
        "timeout": 10,
    }
    detail_args = run.call_args_list[1]
    assert detail_args.args[0][:3] == ["loginctl", "show-session", "2"]
    assert detail_args.kwargs["env"]["LC_ALL"] == "C"
    assert detail_args.kwargs["env"]["TZ"] == "UTC"
    assert detail_args.kwargs["check"] is True


def test_parse_ssh_properties():
    assert sessions.parse_loginctl_output(PROPERTIES) == [
        Session(
            user="alice",
            kind="ssh",
            tty="pts/0",
            remote_host="host.example",
            since=datetime(2026, 11, 9, 6, 34, 13, tzinfo=UTC),
        )
    ]


@pytest.mark.parametrize(
    ("service", "remote", "expected"),
    [
        ("gdm-password", "no", "local"),
        ("other", "yes", "remote"),
        ("sshd", "no", "ssh"),
    ],
)
def test_session_kind(service, remote, expected):
    text = PROPERTIES.replace("Service=sshd", f"Service={service}").replace(
        "Remote=yes", f"Remote={remote}"
    )
    assert sessions.parse_loginctl_output(text)[0].kind == expected


def test_empty_optional_values():
    text = (
        PROPERTIES.replace("RemoteHost=host.example", "RemoteHost=")
        .replace("TTY=pts/0", "TTY=")
        .replace("Timestamp=Mon 2026-11-09 06:34:13 UTC", "Timestamp=")
    )
    result = sessions.parse_loginctl_output(text)[0]
    assert result.remote_host is None
    assert result.tty is None
    assert result.since is None


def test_greeter_is_not_a_user_session():
    assert (
        sessions.parse_loginctl_output(
            PROPERTIES.replace("Class=user", "Class=greeter")
        )
        == []
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        PROPERTIES.replace("Remote=yes", "Remote=maybe"),
        PROPERTIES.replace("Name=alice", "Name="),
        PROPERTIES.replace("Timestamp=Mon 2026-11-09 06:34:13 UTC", "Timestamp=bad"),
        PROPERTIES + "Name=bob\n",
    ],
)
def test_invalid_properties_fail(text):
    with pytest.raises(ValueError):
        sessions.parse_loginctl_output(text)


def test_no_sessions(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""))
    monkeypatch.setattr(sessions.subprocess, "run", run)
    assert sessions.list_login_sessions() == []
    assert run.call_count == 1


def test_multiple_sessions(monkeypatch):
    run = Mock(
        side_effect=[
            subprocess.CompletedProcess(
                [], 0, stdout="1 1000 alice\n2 1001 bob\n", stderr=""
            ),
            subprocess.CompletedProcess([], 0, stdout=PROPERTIES, stderr=""),
            subprocess.CompletedProcess(
                [], 0, stdout=PROPERTIES.replace("alice", "bob"), stderr=""
            ),
        ]
    )
    monkeypatch.setattr(sessions.subprocess, "run", run)
    assert [s.user for s in sessions.list_login_sessions()] == ["alice", "bob"]


def test_command_failure_propagates(monkeypatch):
    error = subprocess.CalledProcessError(1, ["loginctl"])
    monkeypatch.setattr(sessions.subprocess, "run", Mock(side_effect=error))
    with pytest.raises(subprocess.CalledProcessError):
        sessions.list_login_sessions()


def test_disappearing_session_propagates_failure(monkeypatch):
    run = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 0, stdout="2 1000 alice\n", stderr=""),
            subprocess.CalledProcessError(1, ["loginctl", "show-session", "2"]),
        ]
    )
    monkeypatch.setattr(sessions.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        sessions.list_login_sessions()


def test_invalid_session_row_fails(monkeypatch):
    run = Mock(
        return_value=subprocess.CompletedProcess([], 0, stdout="bad\n", stderr="")
    )
    monkeypatch.setattr(sessions.subprocess, "run", run)
    with pytest.raises(ValueError, match="session row"):
        sessions.list_login_sessions()


def test_find_vscode_users(monkeypatch):
    output = """\
1000 /home/alice/.vscode-server/cli/servers/Stable-123/server/node server-main.js
1000 /usr/bin/node /home/alice/.vscode-server/bin/server-main.js
1001 /bin/sh /home/bob/.vscode-server-insiders/bin/code-server
1002 /usr/bin/cat /home/bob/.vscode-server/settings.json
1003 /usr/bin/grep .vscode-server
1004 /home/x/.vscode-server-backup/bin/node
1005 /usr/bin/node /home/x/other.js --extension=.vscode-server/file
"""
    run = Mock(
        return_value=subprocess.CompletedProcess([], 0, stdout=output, stderr="")
    )
    lookup = Mock(
        side_effect=lambda uid: {
            1000: Mock(pw_name="alice"),
            1001: Mock(pw_name="bob"),
        }[uid]
    )
    monkeypatch.setattr(sessions.subprocess, "run", run)
    monkeypatch.setattr(sessions.pwd, "getpwuid", lookup)

    assert sessions.find_vscode_users() == {"alice", "bob"}
    assert lookup.call_count == 2
    run.assert_called_once_with(
        ["ps", "-eo", "euid=,args=", "-ww"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )


def test_find_vscode_users_no_processes(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""))
    monkeypatch.setattr(sessions.subprocess, "run", run)
    assert sessions.find_vscode_users() == set()


@pytest.mark.parametrize("output", ["not-a-uid command\n", "1000\n", "1000  \n"])
def test_find_vscode_users_invalid_output(monkeypatch, output):
    run = Mock(
        return_value=subprocess.CompletedProcess([], 0, stdout=output, stderr="")
    )
    monkeypatch.setattr(sessions.subprocess, "run", run)
    with pytest.raises(ValueError, match="ps process"):
        sessions.find_vscode_users()


def test_find_vscode_users_propagates_ps_failure(monkeypatch):
    error = subprocess.CalledProcessError(1, ["ps"])
    monkeypatch.setattr(sessions.subprocess, "run", Mock(side_effect=error))
    with pytest.raises(subprocess.CalledProcessError):
        sessions.find_vscode_users()


def test_find_vscode_users_unmapped_uid_fails(monkeypatch):
    output = "9999 /home/alice/.vscode-server/bin/node\n"
    monkeypatch.setattr(
        sessions.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 0, stdout=output, stderr="")),
    )
    monkeypatch.setattr(sessions.pwd, "getpwuid", Mock(side_effect=KeyError(9999)))
    with pytest.raises(KeyError):
        sessions.find_vscode_users()


def test_find_vscode_users_detects_real_process(tmp_path):
    executable = tmp_path / ".vscode-server" / "bin" / "node"
    executable.parent.mkdir(parents=True)
    executable.symlink_to(sys.executable)
    with subprocess.Popen(
        [str(executable), "-c", "print('ready', flush=True); input()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as process:
        try:
            assert process.stdout is not None
            assert process.stdout.readline() == "ready\n"
            assert pwd.getpwuid(os.geteuid()).pw_name in sessions.find_vscode_users()
        finally:
            process.terminate()
            process.wait(timeout=10)


def test_merge_vscode_preserves_logins_and_adds_process_signals():
    login = Session(
        user="alice",
        kind="ssh",
        tty="pts/0",
        remote_host="host.example",
        since=datetime(2026, 11, 9, 6, 34, 13, tzinfo=UTC),
    )
    second_login = Session(user="alice", kind="local", tty="tty1")
    original = [login, second_login, Session(user="charlie", kind="ssh")]
    result = sessions.merge_vscode_sessions(original, {"bob", "alice"})
    assert result == [
        *original,
        Session(user="alice", kind="vscode"),
        Session(user="bob", kind="vscode"),
    ]
    assert original == [login, second_login, Session(user="charlie", kind="ssh")]


def test_merge_vscode_empty_inputs():
    assert sessions.merge_vscode_sessions([], set()) == []
    assert sessions.merge_vscode_sessions([], {"alice"}) == [
        Session(user="alice", kind="vscode")
    ]
    original = [Session(user="bob", kind="ssh")]
    assert sessions.merge_vscode_sessions(original, set()) == original
    assert sessions.merge_vscode_sessions(original, set()) is not original


def test_merge_vscode_is_idempotent():
    original = [Session(user="alice", kind="vscode"), Session(user="bob", kind="ssh")]
    result = sessions.merge_vscode_sessions(original, {"alice", "bob"})
    assert result == [*original, Session(user="bob", kind="vscode")]
    assert sessions.merge_vscode_sessions(result, {"alice", "bob"}) == result
