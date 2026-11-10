"""``vm-extend``: push the end of the current claim."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import UTC
from pathlib import Path

from gpuboard_agent.cli._common import (
    add_config_argument,
    add_duration,
    claim_lock,
    current_user,
    parse_duration,
)
from gpuboard_agent.config import load_agent_config
from gpuboard_common.claimfile import is_planned, load_claim, save_claim
from gpuboard_common.timeutil import now


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(prog="vm-extend", description="Extend a claim.")
    parser.add_argument("duration", help="e.g. 2h")
    add_config_argument(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``vm-extend``."""
    args = build_parser().parse_args(argv)
    try:
        config = load_agent_config(Path(args.config) if args.config else None)
        duration = parse_duration(args.duration)
        user = current_user()
        with claim_lock(config.claim_path):
            claim = load_claim(config.claim_path)
            if claim is None:
                raise ValueError("no claim exists")
            if claim.owner != user:
                raise ValueError(f"claim belongs to {claim.owner}, not {user}")
            current = now()
            if is_planned(claim, current):
                raise ValueError("cannot extend a planned claim yet")
            base = (
                claim.end
                if claim.end.astimezone(UTC) > current.astimezone(UTC)
                else current
            )
            claim = replace(claim, end=add_duration(base, duration))
            save_claim(config.claim_path, claim)
    except (OSError, ValueError, KeyError, OverflowError) as exc:
        print(f"vm-extend: {exc}", file=sys.stderr)
        return 1
    print(f"Claim extended until {claim.end.isoformat(timespec='seconds')}")
    return 0
