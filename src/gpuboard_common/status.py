"""Pure status derivation: the heart of the system."""

from __future__ import annotations

from datetime import datetime

from gpuboard_common.claimfile import is_active, is_expired
from gpuboard_common.models import VmSnapshot, VmStatus


def users_with_activity(snapshot: VmSnapshot) -> set[str]:
    """Return all users that have a session or a GPU process on the VM."""
    users = {session.user for session in snapshot.sessions}
    users.update(proc.effective_owner for proc in snapshot.gpu_processes)
    return users


def derive_status(snapshot: VmSnapshot, now: datetime) -> VmStatus:
    """Derive the VM status from one snapshot.

    Rules, in order:

    1. VM stopped or agent unreachable -> ``OFF_UNREACHABLE``.
    2. Active claim: GPU process of another user -> ``CONFLICT``, else
       ``CLAIMED`` (foreign SSH sessions alone are only a warning).
    3. Expired claim: owner still active -> ``CLAIM_EXPIRED``; only others
       active -> ``UNCLAIMED_USAGE``; nobody -> ``FREE`` (awaiting cleanup).
    4. No claim, or a claim that has not started yet: any activity ->
       ``UNCLAIMED_USAGE``, otherwise ``FREE``.

    ``now`` must be timezone-aware.
    """
    if not snapshot.reachable or not snapshot.vm_running:
        return VmStatus.OFF_UNREACHABLE

    users = users_with_activity(snapshot)
    claim = snapshot.claim

    if claim is not None and is_active(claim, now):
        foreign_gpu = any(
            p.effective_owner != claim.owner for p in snapshot.gpu_processes
        )
        return VmStatus.CONFLICT if foreign_gpu else VmStatus.CLAIMED

    if claim is not None and is_expired(claim, now):
        if claim.owner in users:
            return VmStatus.CLAIM_EXPIRED
        return VmStatus.UNCLAIMED_USAGE if users else VmStatus.FREE

    return VmStatus.UNCLAIMED_USAGE if users else VmStatus.FREE
