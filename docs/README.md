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
7. If using SSH pull, create an unprivileged `gpuboard` user for the collector;
   it only needs to run `vm-agent`. The transport is still under consideration.
8. Collector host: `pip install ".[collector]"`, copy
   `collector/collector.example.yaml` and
   `collector/gpu-board-collector.service`.
9. Proxmox: create an API token with the `PVEAuditor` role per node.

## Data ownership and status

The VM agent collects a snapshot of local facts, including the local claim.
The collector owns Proxmox inventory, determines whether a current snapshot
was received, and derives the VM status. `VmInventory.running` represents
Proxmox's running state; a missing snapshot is not the same as an idle VM.
Stopped or unavailable VMs get `OFF_UNREACHABLE`, even if an old snapshot
exists. `VmEntry` combines inventory, the current snapshot when available,
the derived status and any collection error.

The planned `vm-status` and MOTD clients display the collector's latest
observations and derived status, with a collection timestamp. A local claim
change can take time to reach the collector. Clients must indicate stale or
unavailable results and use a short timeout so login is not held up; they may
show the local claim separately, without presenting it as a collector status.
Status freshness thresholds and the snapshot transport have not been decided.

## Agent snapshot

Run `vm-agent` for one JSON snapshot, or `vm-agent --config /path/agent.yaml`
to select a config. The optional default path is `/etc/gpuboard/agent.yaml`;
an explicitly selected missing file is an error. Configuration must be a YAML
mapping containing only the keys in `agent/agent.example.yaml`. Claim paths
must be absolute; durations must be finite and positive, except an idle grace
of zero is allowed. Existing defaults apply when a setting is omitted.

The JSON contract has `schema_version: 1`, `hostname`, `collected_at`,
`gpu_model`, `sessions`, `gpu_processes`, `containers`, and `claim`.
Timestamps include UTC offsets, optional fields use `null`, and collections
are arrays. `claim` is the latest local claim or `null`. The reader rejects
unknown schema versions, missing fields and invalid data. `hostname` is an
observation, not a verified Proxmox VM identity; stable mapping and
authentication remain collector-side design work.

The agent collects its sources sequentially, so the snapshot is not atomic.
The collection timestamp is recorded after collection, not at each individual
observation. Source failures cause a nonzero exit and an error on stderr,
without emitting a partial snapshot. Docker and NVIDIA tools, logind, and
adequate permissions are required. A missing claim file means no claim.

## Login session collection

The agent's `list_login_sessions()` uses `loginctl list-sessions`, followed by
`loginctl show-session` for each session. It reports user-class sessions,
excluding greeters and other system classes. The PAM service identifies SSH
sessions; other remotely marked sessions are labeled `remote`, and the rest
are labeled `local`. Start times are stored in UTC. Command failures,
malformed output and sessions that disappear during collection are reported
as errors, not treated as an empty session list.

This currently requires systemd-logind; there is no `who` fallback.
`find_vscode_users()` also scans process executable and script paths under
`.vscode-server` or `.vscode-server-insiders`, using numeric process owners
to resolve user names. Its results are a best-effort activity signal, not proof
of an active connection: processes can linger after a disconnect, and procfs
permissions can limit visibility. `merge_vscode_sessions()` keeps login
sessions intact and adds one `vscode` entry per detected user; this entry is a
process signal, not a confirmed login. The current status rules count that
entry as activity, so a lingering process can prevent a VM from appearing
free. With SSH pull, the
collector's own SSH login may appear as a session; filtering service accounts
and handling that self-observation still need a design before status collection
is integrated.

## Docker observation

The agent lists running containers using `docker ps`, then uses `docker inspect`
to obtain exact labels, including values containing commas. Docker CLI and
daemon errors are reported rather than interpreted as an empty container list.
If a container stops or disappears during collection, that collection fails
and should be retried by the caller. Cgroup mapping recognizes Docker
systemd scopes and `/docker/<id>` paths; it does not identify other runtimes.
Only running Docker containers are listed.

The agent needs Docker API access to list and inspect containers. Membership in
the Docker socket group effectively grants root-level control of the host;
do not grant it casually to all users. An appropriately restricted Docker API
proxy or a dedicated privileged collection mechanism needs to be evaluated
before deployment.

## GPU observation

The GPU collector uses `nvidia-smi` to query the model and **compute**
processes, then resolves each PID's effective Linux user with `ps` and maps
its `/proc/<pid>/cgroup` against the supplied Docker inventory. It records
container labels when a Docker match exists; Docker IDs are strings.
Processes that disappear during collection and recognized containers missing
from the inventory cause a collection error, not an idle result. Collection
is not atomic: processes may exit or PIDs may be reused between commands.
Unrecognized container runtime cgroup layouts are not attributed to Docker.
The query does not cover graphics-only processes, GPU utilization, or
containers that have no GPU compute process. Agent snapshot integration
remains to be implemented.

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
