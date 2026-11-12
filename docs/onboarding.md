# Onboard a Linux GPU VM (MVP)

This guide adds one existing Proxmox GPU VM to an **already working collector**.
The initial setup has been tested on one VM. Repeat this manual procedure for
each Linux VM; do not use it for Windows guests. No GPU or workload is stopped
or reconfigured by these steps.

The examples assume an Ubuntu/systemd guest, a collector at
`192.0.2.10:8080`, and installation under `/opt/gpuboard/venv`. All addresses,
VM IDs, hostnames and usernames below are fictional examples. The `192.0.2.0/24`
network is reserved for documentation and will not reach your machines. Replace
these values and the Git revision with your own before running commands.
Commands are labeled by the machine on which they run.

## Before starting

Record:

| Item | Example | Notes |
| --- | --- | --- |
| Proxmox VM ID and node | `901`, `pve-a` | The ID must be unique cluster-wide. |
| VM SSH address | `192.0.2.20` | Use a stable address reachable from the collector. |
| Collector URL | `http://192.0.2.10:8080/status.json` | Must be reachable from the VM. |
| Collector account and key | `gpuboard`, `/var/lib/gpuboard/.ssh/id_ed25519` | These are the current collector's settings, not the VM's personal accounts. |
| Personal users | `alice`, `bob` | Identify the people who may create claims. |
| Approved source revision | Git commit ID | Use the same reviewed version across VMs. |

The collector must already have working Proxmox API access to the VM's node,
the `gpuboard` SSH key and a running service. Check the actual `ssh_user`,
`ssh_key`, `agent_command`, `status_path` and `vm_addresses` in its existing
`/etc/gpuboard/collector.yaml`; this guide's commands assume the example
values above and `/opt/gpuboard/venv/bin/vm-agent`. The collector must be able
to reach the VM on SSH port 22, and the VM must be able to reach the collector
endpoint.

**MVP security and limitations:**

- This is visibility, not access control. A claim does not prevent login or
  stop anyone from using a GPU. Coordinate with current users before testing.
- The status endpoint has **no authentication or TLS** and may expose
  usernames, sessions, claims and container metadata. Limit network access
  according to your organization's requirements; `0.0.0.0` means all IPv4
  interfaces, not just the VPN. Do not expose it publicly.
- The collector's VM account is added to the Docker group for the MVP.
  **Docker socket access is root-equivalent** on that VM. Protect the
  collector and its private key accordingly; restricted observation is
  tracked in [issue #7](https://github.com/Autonomous-System-ZHAW/iminurvm/issues/7).
- Cleanup can remove an expired idle claim. Containers without GPU compute
  activity alone do not prevent removal; lingering sessions can prevent it.
  Real idle deletion has not yet been verified during initial rollout. See the
  [cleanup guide](../agent/README.md#expired-claim-cleanup) before enabling it.
- GPU process owner attribution may be a host UID such as `uid:2345`, which
  cannot identify the human using a container and can cause a `CONFLICT`.
  GPU compute processes, not graphics-only or paused workloads, are observed.
  A `FREE` status is not a guarantee that the claim file can be replaced.

## 1. Check the GPU VM

On the **GPU VM**, use a personal administrator account with `sudo`:

```sh
hostname
python3 --version
systemctl is-active ssh
systemctl is-active systemd-logind
nvidia-smi
sudo docker ps
timedatectl status
curl -i --max-time 5 http://192.0.2.10:8080/status.json
```

Python 3.11 or newer, systemd-logind, the NVIDIA driver and working
`nvidia-smi`, Docker CLI and daemon, OpenSSH and synchronized time are needed.
The Docker check is read-only. The response can contain sensitive data; do not
paste it into public logs. HTTP 503 means the collector has not completed a
successful poll since startup. Fix prerequisites before proceeding.

Install the basic packaging tools if missing:

```sh
sudo apt update
sudo apt install git python3-venv
```

Check for an existing installation **before** creating accounts or copying
files:

```sh
getent passwd gpuboard
getent group vm-claim
ls -ld /var/lib/gpuboard /etc/gpuboard /opt/gpuboard/venv
```

Some paths or accounts may not exist on a new VM. If they do, inspect and
preserve their contents and ownership. Do not overwrite another application's
account, configuration, SSH keys, claim file or installation.

## 2. Install the agent and user commands

On the **GPU VM**, clone the repository as an administrator. If a checkout
already exists, inspect it with `git status --short` and preserve local changes.
Use your approved repository access method:

```sh
cd ~
git clone https://github.com/Autonomous-System-ZHAW/iminurvm.git
cd iminurvm
git fetch origin
git log -1 --oneline origin/main
```

Select the reviewed commit instead of implicitly deploying an unreviewed
branch tip. Replace `<commit>` with its actual ID:

```sh
git checkout --detach <commit>
sudo python3 -m venv /opt/gpuboard/venv
sudo /opt/gpuboard/venv/bin/pip install .
/opt/gpuboard/venv/bin/vm-agent --help
/opt/gpuboard/venv/bin/vm-status --help
```

For an existing installation, ensure `/opt/gpuboard/venv` is the intended
root-owned environment, then reinstall with
`sudo /opt/gpuboard/venv/bin/pip install --upgrade .`; do not recreate or
replace someone else's environment. The installation is not editable. Keep
the environment, its executables, configuration and source used for root-run
services protected from untrusted modification.

Users may run commands by full path. To make the user-facing commands available
without the full path, first check for name conflicts:

```sh
ls -l /usr/local/bin/vm-claim /usr/local/bin/vm-extend \
  /usr/local/bin/vm-release /usr/local/bin/vm-status /usr/local/bin/vm-motd
```

Missing paths are expected on a new VM. Only after confirming that none exist,
create the links:

```sh
sudo ln -s /opt/gpuboard/venv/bin/vm-claim /usr/local/bin/vm-claim
sudo ln -s /opt/gpuboard/venv/bin/vm-extend /usr/local/bin/vm-extend
sudo ln -s /opt/gpuboard/venv/bin/vm-release /usr/local/bin/vm-release
sudo ln -s /opt/gpuboard/venv/bin/vm-status /usr/local/bin/vm-status
sudo ln -s /opt/gpuboard/venv/bin/vm-motd /usr/local/bin/vm-motd
```

If a name already exists, inspect it and resolve the conflict deliberately;
do not overwrite it. `vm-agent` and `vm-cleanup` are invoked by absolute path
in the configuration and service below.

## 3. Prepare the claim directory

On the **GPU VM**, if `vm-claim` and `/var/lib/gpuboard` do not already
exist, create them:

```sh
sudo groupadd vm-claim
sudo install -d -m 2775 -o root -g vm-claim /var/lib/gpuboard
```

If either already exists, inspect it first; do not reset permissions or remove
existing claims. The expected claim directory is `root:vm-claim` with mode
`2775`. Add each authorized personal user, replacing the example names:

```sh
sudo usermod -aG vm-claim alice
sudo usermod -aG vm-claim bob
getent group vm-claim
ls -ld /var/lib/gpuboard
```

Users must start a **new login session** to pick up their new group membership;
verify with `id` in that session. All users in this group can write the claim
directory: ownership is cooperative, not a security boundary. The collector
account needs read access to claims but does not need group membership.

## 4. Configure the agent

On the **GPU VM**, create the configuration directory and, only if the
configuration does not exist, copy the example:

```sh
sudo install -d -m 755 -o root -g root /etc/gpuboard
sudo install -m 644 -o root -g root agent/agent.example.yaml /etc/gpuboard/agent.yaml
```

If `/etc/gpuboard/agent.yaml` already exists, **do not run the copy command**;
edit it instead. Set the actual VM ID and collector URL, and exclude only the
dedicated collector account's session signals:

```sh
sudoedit /etc/gpuboard/agent.yaml
```

Example settings (merge into the existing YAML; do not duplicate keys):

```yaml
claim_path: /var/lib/gpuboard/claim.json
excluded_session_users:
  - gpuboard
collector_status_url: http://192.0.2.10:8080/status.json
vmid: 901
```

Replace `901` and the URL. Retain any existing settings. Do not exclude
personal users; that would hide their sessions from both the collector and
cleanup. The exclusion never hides GPU processes. The PAM auto-claim hook is
not part of this rollout and is not implemented.

Verify the settings load:

```sh
/opt/gpuboard/venv/bin/python -c 'from gpuboard_agent.config import load_agent_config; c = load_agent_config(); print("VM ID:", c.vmid, "claim:", c.claim_path, "excluded sessions:", c.excluded_session_users, "collector:", c.collector_status_url)'
```

## 5. Prepare collector access on the VM

On the **GPU VM**, create a dedicated account if it does not already exist:

```sh
sudo adduser --disabled-password --gecos "" gpuboard
sudo usermod -aG docker gpuboard
id gpuboard
```

If `gpuboard` already exists, verify it is the intended dedicated account and
inspect its home directory before changing it. Docker group membership provides
root-equivalent privileges. Do not add ordinary users to Docker solely for this
tool. `--disabled-password` avoids setting a password; SSH key login also
depends on the VM's SSH/PAM account policy. Do not enable a shared password to
work around authentication failures.

On the **collector**, display its public key:

```sh
sudo -u gpuboard -H cat /var/lib/gpuboard/.ssh/id_ed25519.pub
```

On the **GPU VM**, prepare the SSH directory and edit the key file:

```sh
sudo install -d -m 700 -o gpuboard -g gpuboard /home/gpuboard/.ssh
sudoedit /home/gpuboard/.ssh/authorized_keys
```

Add the collector's **public** key as a new line. Preserve existing authorized
keys. Never copy or share the collector's private key. Then make the file
readable by the service account:

```sh
sudo chown gpuboard:gpuboard /home/gpuboard/.ssh/authorized_keys
sudo chmod 600 /home/gpuboard/.ssh/authorized_keys
sudo ssh-keygen -lf /home/gpuboard/.ssh/authorized_keys
```

Check that the intended public-key fingerprint is listed. If the account uses
a different home directory, use that account's actual SSH path instead.

## 6. Verify SSH and agent from the collector

On the **GPU VM**, obtain its ED25519 host-key fingerprint via a trusted
console or an already verified administrator connection:

```sh
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

On the **collector**, connect interactively as its service account, replacing
`192.0.2.20` with the new VM's address:

```sh
sudo -u gpuboard -H ssh -i /var/lib/gpuboard/.ssh/id_ed25519 \
  -o IdentitiesOnly=yes -o HostKeyAlgorithms=ssh-ed25519 \
  gpuboard@192.0.2.20
```

Compare the displayed fingerprint with the one obtained on the VM. Accept it
**only if it matches**. If SSH reports a changed host key, stop and investigate;
do not blindly delete the old key. Exit the session after authentication.
If login fails, check the VM's SSH logs, account policy, key fingerprint and
ownership/modes of its home, `.ssh` directory and `authorized_keys`.

On the **collector**, verify the exact non-interactive pull and JSON output:

```sh
umask 077
CHECK_FILE=$(mktemp "$HOME/gpuboard-snapshot.XXXXXX")
sudo -u gpuboard -H ssh -T -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes \
  -i /var/lib/gpuboard/.ssh/id_ed25519 \
  gpuboard@192.0.2.20 /opt/gpuboard/venv/bin/vm-agent \
  > "$CHECK_FILE"
```

Check that SSH exited successfully before continuing; if it failed, investigate
the error and remove the temporary file. Otherwise validate the JSON and
inspect a limited summary locally:

```sh
python3 -m json.tool "$CHECK_FILE" > /dev/null
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("hostname:", d["hostname"], "GPU:", d["gpu_model"]); print("session users:", sorted({s["user"] for s in d["sessions"]})); print("GPU process users:", sorted({p["user"] for p in d["gpu_processes"]}))' "$CHECK_FILE"
rm "$CHECK_FILE"
```

The temporary file is private and can contain sensitive snapshot data. Agent
warnings on stderr, such as an unmapped UID, are not JSON. Check that real
users appear and the collector account's session is absent; the latter
filtering does not apply to GPU processes. Source errors must be fixed, not
interpreted as idle.

## 7. Add the VM to collector inventory

In the **Proxmox UI**, add the exact tag `gpu` to this VM without removing its
other tags. The collector reads tagged QEMU VMs, including stopped VMs; it
does not discover addresses automatically. The Proxmox token must be able to
see the VM and its configuration.

On the **collector**, edit its existing configuration:

```sh
sudoedit /etc/gpuboard/collector.yaml
```

Under the existing `vm_addresses` mapping, add the new ID and address, for
example:

```yaml
vm_addresses:
  901: 192.0.2.20
  902: 192.0.2.21
```

Keep all other mappings and settings. Do **not** create a second
`vm_addresses` key. Ensure `agent_command` matches the VM installation path,
and `ssh_user` and `ssh_key` match the account and key just tested. YAML
rejects duplicate keys. The service reloads configuration between polls;
listener host/port changes require a restart.

Wait for a polling cycle, then on the **collector**:

```sh
systemctl is-active gpu-board-collector
sudo journalctl -u gpu-board-collector -n 40 --no-pager
```

On the **GPU VM**:

```sh
/opt/gpuboard/venv/bin/vm-status --verbose
/opt/gpuboard/venv/bin/vm-motd
```

Check that the correct VM ID appears, board and snapshot freshness are
`FRESH`, and the snapshot has the expected GPU and users. A running VM with
an SSH or agent failure appears `UNREACHABLE`, with details in `--verbose`;
a stopped VM appears `OFF`. The collector may take longer than one configured
interval between cycle starts. Avoid sharing full status responses publicly.

## 8. Install the login banner

On the **GPU VM**, inspect any existing hook before copying. From the
repository checkout:

```sh
ls -l /etc/profile.d/gpuboard-motd.sh
```

If no file exists at that path:

```sh
sudo install -m 644 motd/gpuboard-motd.sh /etc/profile.d/gpuboard-motd.sh
```

For interactive **non-login Bash** shells, including typical VS Code Remote
terminals, edit `/etc/bash.bashrc` and add the following line once, after
checking existing configuration:

```sh
. /etc/profile.d/gpuboard-motd.sh
```

Test a new interactive SSH login and a new VS Code Bash terminal. Non-Bash
shells need separate integration; non-interactive agent SSH must remain clean.
The banner currently appears in each new interactive shell; improvement is
tracked in [issue #10](https://github.com/Autonomous-System-ZHAW/iminurvm/issues/10).
The hook uses GNU `timeout` to avoid indefinitely blocking shell startup.

## 9. Test claims, then enable cleanup

In a **new personal-user session on the GPU VM**, check `id` includes
`vm-claim`. Coordinate with current users and do not overwrite or release
someone else's claim. Then create a short test claim:

```sh
/opt/gpuboard/venv/bin/vm-claim --project onboarding-test --message "Testing gpu-board" --duration 15m
```

After a successful poll, check `vm-motd` and `vm-status --verbose`; another
user can check the ownership warning. Release the claim as its owner:

```sh
/opt/gpuboard/venv/bin/vm-release
```

Confirm it disappears after another poll. Release does not stop workloads.
If a claim already exists, contact its owner; do not force-release it for a
test. For normal use, see the [claim commands](../cli/README.md#claim-commands).

After reviewing the cleanup policy and any existing unit files, install and
enable the timer on the **GPU VM**:

```sh
sudo install -m 644 agent/gpuboard-cleanup.service /etc/systemd/system/
sudo install -m 644 agent/gpuboard-cleanup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gpuboard-cleanup.timer
systemctl is-enabled gpuboard-cleanup.timer
systemctl is-active gpuboard-cleanup.timer
systemctl list-timers gpuboard-cleanup.timer --no-pager
sudo journalctl -u gpuboard-cleanup.service -n 20 --no-pager
```

The service runs as root every approximately five minutes. `No claim removed`
is normal when there is no eligible claim and does **not** prove idle deletion.
Test actual deletion separately in a coordinated idle window, after expiry and
the configured grace period (30 minutes by default). Do not disconnect other
users or stop their workloads to conduct a test.

## 10. Operational handover

- Tell users where to find `vm-claim`, `vm-extend`, `vm-release` and
  `vm-status`, and explain the [team rules](../README.md#team-rules).
- Record the VM ID, address, approved revision, onboarding date and any
  deviations in your normal operations inventory. Collect feedback on status
  and banner usability.
- On update, fetch and check out an approved commit, reinstall the package,
  review changed hooks and units, and retest. Existing claim files and config
  are outside the checkout; do not overwrite them. Restart the cleanup service
  only if needed; the timer invokes the installed executable on its next run.
- Do not treat this pilot as proof of availability or security for untrusted
  networks. Watch collector and cleanup logs, stale warnings, time
  synchronization and unmapped UIDs; validate remaining edge cases as rollout
  proceeds. Automation and easier onboarding are tracked in
  [issue #6](https://github.com/Autonomous-System-ZHAW/iminurvm/issues/6).
