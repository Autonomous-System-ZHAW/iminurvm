"""``vm-release``: give the VM back."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gpuboard_agent.cli._common import add_config_argument, claim_lock, current_user
from gpuboard_agent.config import load_agent_config
from gpuboard_common.claimfile import delete_claim, load_claim


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(prog="vm-release", description="Release a claim.")
    parser.add_argument("--force", action="store_true", help="release someone else's")
    add_config_argument(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``vm-release``."""
    args = build_parser().parse_args(argv)
    try:
        config = load_agent_config(Path(args.config) if args.config else None)
        user = current_user()
        with claim_lock(config.claim_path):
            claim = load_claim(config.claim_path)
            if claim is None:
                raise ValueError("no claim exists")
            if claim.owner != user and not args.force:
                raise ValueError(
                    f"claim belongs to {claim.owner}; use --force to release it"
                )
            delete_claim(config.claim_path)
    except (OSError, ValueError, KeyError) as exc:
        print(f"vm-release: {exc}", file=sys.stderr)
        return 1
    print(f"Released claim held by {claim.owner}")
    return 0
