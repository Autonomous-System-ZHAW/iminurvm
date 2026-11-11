# Roadmap

Phase 0 (this scaffold): layout, tooling, models, `status.py`, `claimfile.py`.

## Phase 1 — agent collectors on a single VM

1. Version 1 snapshot JSON contract implemented; stable VM identity mapping
   remains to be designed for the collector
2. `sessions.py`: logind collection, VS Code process detection and merging
   integrated with the agent; handle collector SSH self-observation
3. `docker.py` implemented: Docker inventory, labels and cgroup mapping;
   decide restricted Docker API access
4. `gpu.py` implemented: `nvidia-smi` compute CSV, PID user and Docker mapping
5. `serialize.py` snapshot (de)serialization, `config.py`, `main.py` (`vm-agent`)
   implemented; initial GPU VM test covered containers and remote sessions.
   Labeled-container and test-claim validation remain.

## Phase 2 — claim commands and cleanup

1. `parse_duration`, `vm-claim`, `vm-extend`, `vm-release` implemented;
   initial VM test confirmed an existing claim cannot be overwritten by
   another user; broader command and permission validation remain
2. `cleanup.py` + systemd timer implemented; validate on a VM

The basic claim workflow and cleanup are the priority. Process-bound claims
and simulation wrappers are deferred as optional enhancements.

## Phase 3 — collector and clients

1. Snapshot transport selected: SSH pull approximately every 30 seconds for
   the MVP; implementation and deployment details remain
2. Collector configuration loader and `gpu`-tagged Proxmox inventory
   implemented; initial inventory tested against both cluster nodes.
   Single SSH snapshot pull tested against VM 111. Opt-in service-account
   session exclusion validated in a VM snapshot. Docker group access
   accepted for the initial test;
   investigate restricted access in issue #7.
3. In-memory merge, status derivation, atomic `status.json` writing and a
   single polling cycle tested against the cluster. Continuous polling with
   retry and freshness assessment implemented; continuous polling tested on
   the cluster. Client integration of freshness remains.
4. Read-only JSON status endpoint implemented; `/metrics` remains.
5. `vm-status` implemented using collector status and freshness. `motd.py` +
   `profile.d` shim remain: show observation time and report stale/unavailable
   data with a short timeout

## Phase 4 — VM rollout

1. Install and configure the agent and collector on their hosts
2. Optional PAM auto-claim (`pam_hook.py`), toggle via config

## Phase 5 (later)

1. Future reservations (planned claims, "from 14:30: alice", MOTD handover
   warning 40 min before)
2. OIDC authentication (Pocket ID)
3. Browser dashboard and claim button (dashboard tracked in issue #8)
4. `vm-run` (`kind: run`, auto-release on exit)
5. `sim-start` / `sim-stop` label wrappers
