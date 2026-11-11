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
7. SSH pull is selected for the MVP but not yet implemented. A dedicated
   collector account and its permissions still need a deployment design,
   including safe Docker observation and session self-observation.
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

The in-memory merge sorts entries by node and VM ID. Stopped VMs have no
snapshot; failed or missing pulls on running VMs produce `OFF_UNREACHABLE`
with an error rather than `FREE`. A successful pull retains its observation
timestamp. Duplicate VM IDs and results for unknown IDs fail the merge.
The merge does not yet assess snapshot freshness.

The board writer can atomically replace `status.json` with version 1 JSON:
`schema_version`, `generated_at` (with UTC offset), and `vms`. Each VM entry
contains `inventory` (including `vmid`, `node`, `running`, `hostpci` and
`address`), `status`, `snapshot` (the version 1 agent snapshot or `null`),
and `error` (`null` or an error message). The nested snapshot retains its own
`collected_at` timestamp. A stopped VM has no snapshot or error; an
unreachable running VM has an error and no snapshot.

The status file is created with mode `0600`; it may contain user names,
container labels and other sensitive information. The target directory must
already exist. Errors propagate, and a failed replacement leaves the previous
file in place; its `generated_at` does not update, so consumers must not
assume an existing file is current. Freshness thresholds, the polling loop and
the public HTTP endpoint are not implemented yet. Do not expose this file or
its contents broadly without evaluating access and data sensitivity.

The planned `vm-status` and MOTD clients display the collector's latest
observations and derived status, with a collection timestamp. A local claim
change can take time to reach the collector. Clients must indicate stale or
unavailable results and use a short timeout so login is not held up; they may
show the local claim separately, without presenting it as a collector status.
Status freshness thresholds have not been decided. SSH snapshot pull is
implemented, but the collector poll loop is not yet implemented.

## Collector configuration

The collector configuration loader reads `collector/collector.example.yaml`
as its example format. It uses `/etc/gpuboard/collector.yaml` by default, or an
explicit path; a missing file is an error. At least one Proxmox node is
required, with a unique node name, host, token ID and absolute token secret
file path. `verify_ssl` defaults to `true`; disabling TLS verification is
insecure and should only be used deliberately in a controlled test.

The `vm_addresses` mapping accepts numeric VM IDs and quoted decimal VM IDs;
values are SSH addresses. Other SSH, polling, status-file and web-listener
settings use the defaults shown in the example when omitted. Paths must be
absolute, timeouts and polling intervals must be finite and positive, and the
listener port must be between 1 and 65535. Unknown fields, duplicate YAML
keys, duplicate node names and duplicate VM IDs are rejected.

Loading configuration does not read the token files, check file permissions,
contact Proxmox or establish SSH connections. The collector service, inventory
poll loop and snapshot transport are not implemented yet; validation does not
prove a configuration will connect successfully.

## Proxmox inventory

The inventory reader requests each configured node's QEMU VM list and each
VM's configuration using a read-only API token. It includes a VM only when its
configuration has the exact Proxmox tag `gpu`, including stopped VMs and VMs
without a `hostpci` entry. Add that tag to each VM intended for the board;
an untagged VM is not included. Other tags do not count as `gpu`.

All `hostpci` values for selected VMs are recorded in numeric slot order.
The `x-vga` option marks a primary GPU, but is not required for GPU compute
passthrough and is not used as a filter. PCI passthrough alone does not prove
the device is a GPU; the agent reports the GPU model separately. An unnamed VM
is displayed as `VM <id>`. Explicit `vm_addresses` are attached to matching
VMs for the future SSH pull.

The reader requires access to the VM list and configuration for every VM it
can see, including untagged VMs, because tags are read from configuration.
Errors reading a node or VM configuration fail the inventory request instead
of returning an incomplete successful result. Permissions can limit which VMs
the API lists; check the token's effective visibility on each node. A VM
migrating between node requests can lead to missing or duplicate observations;
duplicate IDs are rejected and must be retried. The implementation uses a
10-second API request timeout. It has only been tested with mocked responses,
not against the real cluster.

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
free. For SSH pull, the VM can exclude dedicated service-account session
signals using `excluded_session_users` in the agent configuration:

```yaml
excluded_session_users:
  - gpuboard
```

By default the list is empty. Exclusions match exact usernames and apply to
all login sessions and VS Code process signals for those accounts in both
snapshots and cleanup. GPU processes are **not** excluded. Do not list
personal or shared user accounts: their activity would be hidden and cleanup
could remove a claim while they are working. Excluding a service account also
hides its interactive logins, so reserve that account for collection. The
setting does not disable auto-claims or change PAM behavior.

The agent and cleanup must load the same VM-side configuration, normally
`/etc/gpuboard/agent.yaml`. A collector-side SSH setting alone does not set
this option. Keep the config administrator-controlled and verify filtering on
the VM before relying on it. The collector poll loop remains unimplemented.

If a process UID has no username in the VM's user database, the agent reports
it as `uid:<number>` (for example `uid:1234`) and logs a warning on stderr.
This marker identifies a numeric UID, not the person using the process. It
applies both to VS Code process signals and GPU process users; container user
accounts do not necessarily exist on the VM. Even a mapped host username may
not identify the person responsible for a container.

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
do not grant it casually to all users. For the initial proof of concept, a
dedicated collector account may be granted Docker group access on the test VM.
Treat its SSH key and account as root-equivalent: the VPN reduces exposure but
does not limit Docker privileges. Restrict key access and do not share the
account. A restricted Docker API proxy or dedicated privileged observer is a
future investigation: [issue #7](https://github.com/Autonomous-System-ZHAW/iminurvm/issues/7).

## SSH snapshot pull

The collector's SSH pull functions connect to running VMs with explicit
`vm_addresses` mappings; they do not guess an address from the VM name. The
SSH user, key, executable and timeout come from collector configuration.
`agent_command` is a single executable name or path, not a shell command with
arguments; use an absolute path when the agent is in a virtual environment.
The timeout bounds the entire SSH invocation, including the agent's collection,
so increase it if real-world collection takes longer.

The collector uses noninteractive public-key SSH and strict host-key checking.
Install and independently verify each VM's host key in the collector
account's known-hosts file before connecting. On success, agent stderr is
logged as a warning and JSON is validated against the snapshot schema. A
missing address, connection error, timeout, nonzero agent exit or invalid
snapshot is an error for that VM; stopped VMs are not contacted. Pulls run
concurrently with at most eight workers.

An SSH connection can appear as a user session. Set `excluded_session_users`
on the VM for a dedicated collector account as described above; verify the
agent and cleanup use the same configuration. The collector poll loop is not
implemented. A single SSH pull has been tested on VM 111; the session
exclusion still needs real-VM validation.

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
containers that have no GPU compute process. Status derivation uses the
`owner` label as the effective GPU process owner when present.
Without that label, an unmapped UID is considered activity but cannot match a
normal claim owner. An active claim therefore yields `CONFLICT` for that
process, even if it actually belongs to the claim owner; an expired claim may
not be associated with that owner's activity. Set `owner` and `project` labels
when creating containers to improve attribution.

## Permissions model

Only writing the claim needs more than user rights. Simplest sound option:

- `/var/lib/gpuboard/` is `root:vm-claim`, mode `2775` (setgid).
- `claim.json` is mode `0664`, group `vm-claim`.
- Writes are atomic (temp file in the same directory + rename), so the
  directory must be group-writable.
- Claim commands coordinate through a persistent group-writable lock file in
  the same directory; all claim writers must acquire it before reading and
  modifying a claim. This is cooperative, not access control.
- No sticky bit: anybody may extend or release a claim (this is a social
  system; `vm-release` of a foreign claim requires `--force`).
- The cleanup service runs as root for process visibility and claim access.
  Keep its installation and configuration root-owned. The PAM hook also runs
  as root; normal user commands run unprivileged.

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
