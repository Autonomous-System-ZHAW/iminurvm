# agent/

Deployment assets for the per-VM agent. Code: `src/gpuboard_agent/`
(`vm-agent`, collectors in `sessions.py`, `gpu.py`, `docker.py`).
Example config: `agent.example.yaml`.

## Expired-claim cleanup

`vm-cleanup` checks the configured claim once. It removes it only after
`idle_grace_minutes` has elapsed since expiry and no non-excluded login session
or VS Code server process, or any GPU compute process, is detected. A detection error fails
the command and preserves the claim. It does not check Docker containers or
graphics-only GPU processes; a running container with no compute process does
not prevent removal. These observations are not atomic.

To run cleanup periodically, install the package in a root-owned environment
at `/opt/gpuboard/venv`, and copy `gpuboard-cleanup.service` and
`gpuboard-cleanup.timer` to `/etc/systemd/system/`. The service runs as root
for process visibility and claim access, so its executable, Python environment,
and any editable source it loads must not be writable by untrusted users.
Adjust `ExecStart` if the installation is elsewhere; `vm-cleanup --config
/path/to/agent.yaml` selects a non-default configuration. The claim directory
must already exist with the permissions described in the
[install guide](../docs/README.md#permissions-model).

After reviewing the unit and configuration, enable the timer:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now gpuboard-cleanup.timer
systemctl list-timers gpuboard-cleanup.timer
sudo journalctl -u gpuboard-cleanup.service
```

The timer first runs five minutes after boot and then approximately every five
minutes. Running `vm-cleanup` manually from an SSH login will normally detect
that login as activity and leave the claim in place. Closing logind sessions
and lingering VS Code processes can also prevent cleanup.

To ignore a dedicated collector account's login and VS Code session signals,
configure `excluded_session_users` on the VM. The list is empty by default;
GPU processes still prevent cleanup. See
[login session collection](../docs/README.md#login-session-collection) for
the configuration and important restrictions. Use the same configuration for
both `vm-agent` and `vm-cleanup`.

An expired manual or run claim that remains in the file prevents `vm-claim`
from creating a replacement. For user-facing recovery steps and the
distinction between derived status and claim availability, see
[expired claims and blocked claims](../cli/README.md#expired-claims-and-blocked-claims).
