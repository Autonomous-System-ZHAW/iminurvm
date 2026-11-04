# iminurvm

**Ownership & visibility for shared GPU VMs on Proxmox** (project name: gpu-board).

## Context

Two Proxmox nodes, several NVIDIA GPUs (RTX PRO 6000, RTX 5090, RTX A5000,
RTX A4000), each passed through to exactly one Linux VM (**1 VM = 1 GPU**).
Students and staff use the VMs for Isaac Sim, Gazebo/ROS 2 and Blender via SSH
or VS Code Remote-SSH, with personal Linux accounts on every VM.

**Problem:** nobody can tell who is using which VM. GPU utilization is
misleading (a paused Isaac Sim container still belongs to someone), so people
stop each other's containers or start work on busy VMs.

**Goal:** visibility and lightweight ownership, **not enforcement**.

## Core idea: the claim

A claim is a social reservation stored on the VM (owner, project, message,
start, end). It is shown in the login banner and on the dashboard. Three
signals are combined per VM: logged-in sessions (incl. VS Code Remote), actual
GPU usage (mapped to user and Docker container), and the claim.

| Status | Condition |
| --- | --- |
| FREE | no claim, no GPU processes, no sessions |
| CLAIMED | active claim; no GPU process of another user |
| CLAIM_EXPIRED | claim ended but owner still has sessions/processes |
| UNCLAIMED_USAGE | sessions or GPU processes exist but there is no claim |
| CONFLICT | GPU processes from a user other than the claim owner |
| OFF_UNREACHABLE | Proxmox reports VM stopped, or agent not reachable |

The precise rules live in [`status.py`](src/gpuboard_common/status.py).

## Architecture

```
┌─ Proxmox Node A ─────────────┐   ┌─ Proxmox Node B ─────────────┐
│ VM 101  [agent]              │   │ VM 201  [agent]              │
│ VM 102  [agent]              │   │ VM 202  [agent]              │
└──────────────┬───────────────┘   └──────────────┬───────────────┘
               │ Proxmox API (read-only token)     │ SSH pull every ~30 s
               ▼                                   ▼
        ┌──────────── Collector (small LXC / VM "gpu-board") ─────────┐
        │  merge: Proxmox inventory + agent state + claims            │
        │  → status.json → web dashboard (single page, auto-refresh)  │
        │  → /metrics (Prometheus text format, prepared, optional)    │
        └─────────────────────────────────────────────────────────────┘
```

## Team rules

1. Whoever uses a VM or needs it for a later job sets a claim with purpose and
   expiry.
2. Never stop containers or processes of other users without asking — even at
   0 % GPU utilization.
3. Claims always expire. Extend actively if you need longer. Expired claims
   with no sessions and no GPU processes are cleaned up automatically after an
   idle grace period (default 30 min).

## Repository layout

| Path | Content |
| --- | --- |
| `src/gpuboard_common/` | dependency-free models, `status.py`, `claimfile.py` |
| `src/gpuboard_agent/` | `vm-agent`, CLI, MOTD, PAM hook (stdlib + PyYAML) |
| `src/gpuboard_collector/` | collector service and dashboard |
| `agent/`, `cli/`, `motd/`, `pam/`, `collector/` | deployable assets, examples |
| `ansible/` | rollout skeleton |
| `docs/` | [documentation](docs/README.md), [roadmap](docs/ROADMAP.md) |
| `tests/` | pytest suite with fixtures |

## Development

```sh
python -m venv .venv && . .venv/bin/activate
make install   # pip install -e ".[collector,dev]"
make fmt lint test
```

Status: **phase 0 (skeleton)**. Only `status.py` and `claimfile.py` are
implemented; everything else is stubbed. See the [roadmap](docs/ROADMAP.md).

