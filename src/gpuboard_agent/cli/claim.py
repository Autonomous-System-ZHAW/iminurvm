"""``vm-claim``: claim this VM."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gpuboard_agent.cli._common import (
    add_config_argument,
    add_duration,
    claim_lock,
    current_user,
    parse_duration,
    validate_duration,
)
from gpuboard_agent.config import load_agent_config
from gpuboard_common.claimfile import is_planned, load_claim, save_claim
from gpuboard_common.models import Claim
from gpuboard_common.timeutil import now


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (project, message, duration)."""
    parser = argparse.ArgumentParser(prog="vm-claim", description="Claim this VM.")
    parser.add_argument("-p", "--project", default="")
    parser.add_argument("-m", "--message", default="")
    parser.add_argument("-d", "--duration", default=None, help="e.g. 4h, 90m")
    add_config_argument(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``vm-claim``."""
    args = build_parser().parse_args(argv)
    try:
        config = load_agent_config(Path(args.config) if args.config else None)
        duration = (
            parse_duration(args.duration)
            if args.duration is not None
            else validate_duration(config.default_claim_hours)
        )
        user = current_user()
        with claim_lock(config.claim_path):
            existing = load_claim(config.claim_path)
            start = now()
            if existing is not None and (
                existing.kind != "auto" or is_planned(existing, start)
            ):
                raise ValueError(
                    f"claim held by {existing.owner} already exists; "
                    "release it or wait for idle cleanup"
                )
            claim = Claim(
                owner=user,
                project=args.project,
                message=args.message,
                start=start,
                end=add_duration(start, duration),
                kind="manual",
                created_by=user,
                created_at=start,
            )
            save_claim(config.claim_path, claim)
    except (OSError, ValueError, KeyError, OverflowError) as exc:
        print(f"vm-claim: {exc}", file=sys.stderr)
        return 1
    print(f"Claimed by {user} until {claim.end.isoformat(timespec='seconds')}")
    return 0
