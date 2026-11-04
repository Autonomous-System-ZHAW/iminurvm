# Roadmap

Phase 0 (this scaffold): layout, tooling, models, `status.py`, `claimfile.py`.

## Phase 1 — agent collectors, `vm-status`, MOTD on a single VM

1. `sessions.py` (`loginctl`/`who`, `.vscode-server` detection)
2. `docker.py` (`docker ps` JSON, cgroup → container, labels)
3. `gpu.py` (`nvidia-smi` CSV, PID → user)
4. `serialize.py` snapshot (de)serialization, `config.py`, `main.py` (`vm-agent`)
5. `vm-status`, `motd.py` + `profile.d` shim

## Phase 2 — claim commands and cleanup

1. `parse_duration`, `vm-claim`, `vm-extend`, `vm-release`
2. `vm-run` (`kind: run`, auto-release on exit)
3. `sim-start` / `sim-stop` label wrappers
4. `cleanup.py` + systemd timer (idle grace period)

## Phase 3 — collector and dashboard

1. `proxmox.py` (inventory, `hostpci`)
2. `ssh_pull.py` (concurrent, timeouts)
3. `merge.py` + `status.json`
4. `web.py` (dashboard, `/metrics`), `main.py` poll loop, systemd unit

## Phase 4 — rollout

1. Ansible roles `accounts`, `vm-agent`, `collector`
2. Optional PAM auto-claim (`pam_hook.py`), toggle via config

## Phase 5 (later)

1. Future reservations (planned claims, "from 14:30: alice", MOTD handover
   warning 40 min before)
2. OIDC authentication (Pocket ID)
3. Claim button in the dashboard
