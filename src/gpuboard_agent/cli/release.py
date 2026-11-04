"""``vm-release``: give the VM back."""

from __future__ import annotations

import argparse

from gpuboard_agent.cli._common import add_config_argument, not_implemented


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(prog="vm-release", description="Release a claim.")
    parser.add_argument("--force", action="store_true", help="release someone else's")
    add_config_argument(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``vm-release``."""
    build_parser().parse_args(argv)
    return not_implemented("vm-release")  # TODO(phase 2)
