# Roadmap

Phase 0 (this scaffold): layout, tooling, models, `status.py`, `claimfile.py`.

## Phase 1 — agent collectors on a single VM

1. Define a versioned snapshot JSON contract and stable VM identity mapping
2. `sessions.py`: logind collection, VS Code process detection and merging
   implemented; integrate with the agent and handle collector SSH
   self-observation
3. `docker.py` (`docker ps` JSON, cgroup → container, labels)
4. `gpu.py` (`nvidia-smi` CSV, PID → user)
5. `serialize.py` snapshot (de)serialization, `config.py`, `main.py` (`vm-agent`)

## Phase 2 — claim commands and cleanup

1. `parse_duration`, `vm-claim`, `vm-extend`, `vm-release`
2. `vm-run` (`kind: run`, auto-release on exit)
3. `sim-start` / `sim-stop` label wrappers
4. `cleanup.py` + systemd timer (idle grace period)

## Phase 3 — collector and dashboard

1. Decide snapshot transport: SSH pull is the original plan; HTTP push and
   MQTT are alternatives. Push requires a VM service, authentication and
   heartbeat/reconnect handling.
2. `proxmox.py` (inventory, `hostpci`) and snapshot transport
3. `merge.py`: derive status centrally; `status.json` and freshness tracking
4. `web.py`: read-only per-VM status endpoint, dashboard and `/metrics`
5. `vm-status`, `motd.py` + `profile.d` shim: use collector status, show
   observation time and report stale/unavailable data with a short timeout

## Phase 4 — VM rollout

1. Install and configure the agent and collector on their hosts
2. Optional PAM auto-claim (`pam_hook.py`), toggle via config

## Phase 5 (later)

1. Future reservations (planned claims, "from 14:30: alice", MOTD handover
   warning 40 min before)
2. OIDC authentication (Pocket ID)
3. Claim button in the dashboard
