# gpu-board documentation

See the [top-level README](../README.md) for context, status table,
architecture diagram and the **team rules**.

## Install guide (target state, filled in during phase 4)

1. Create the `vm-claim` group and add every personal account to it.
2. `install -d -m 2775 -o root -g vm-claim /var/lib/gpuboard`
3. `pip install .` into a venv (or system-wide) and symlink the console
   scripts into `/usr/local/bin`.
4. Copy `agent/agent.example.yaml` to `/etc/gpuboard/agent.yaml`.
5. Install `motd/gpuboard-motd.sh` as `/etc/profile.d/gpuboard-motd.sh`
   (this also covers VS Code Remote terminals).
6. Optional: append `pam/sshd.snippet` to `/etc/pam.d/sshd`. Disable via
   `pam_auto_claim_enabled: false` or by removing the line.
7. Create an unprivileged `gpuboard` user for the collector's SSH pull; it only
   needs to run `vm-agent`.
8. Collector host: `pip install ".[collector]"`, copy
   `collector/collector.example.yaml` and
   `collector/gpu-board-collector.service`.
9. Proxmox: create an API token with the `PVEAuditor` role per node.

All of this is automated by `ansible/`.

## Permissions model

Only writing the claim needs more than user rights. Simplest sound option:

- `/var/lib/gpuboard/` is `root:vm-claim`, mode `2775` (setgid).
- `claim.json` is mode `0664`, group `vm-claim`.
- Writes are atomic (temp file in the same directory + rename), so the
  directory must be group-writable.
- No sticky bit: anybody may extend or release a claim (this is a social
  system; `vm-release` of a foreign claim requires `--force`).
- The PAM hook runs as root; everything else runs unprivileged.

## Claim file format

`/var/lib/gpuboard/claim.json` (path configurable) is the source of truth.
All timestamps are ISO 8601 **with UTC offset**; display is Europe/Zurich.

```json
{
  "owner": "alice",
  "project": "gazebo-playground",
  "message": "just experimenting, feel free to ask",
  "start": "2026-11-04T09:17:00+01:00",
  "end": "2026-11-04T13:17:00+01:00",
  "kind": "manual",
  "pid": null,
  "created_by": "alice",
  "created_at": "2026-11-04T09:17:00+01:00"
}
```

| Field | Meaning |
| --- | --- |
| `kind` | `manual`, `auto` (PAM soft claim) or `run` (bound to `vm-run`) |
| `pid` | required for `run`, otherwise `null` |
| `start` | currently always "now"; a future `start` is a *planned* claim |
| `end` | must be after `start`; the claim is expired once `now >= end` |

A planned claim (`start > now`) is valid but ignored by status derivation.
Scheduling itself is not implemented yet.
