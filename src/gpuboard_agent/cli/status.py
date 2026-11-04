"""``vm-status``: show claim, sessions and GPU usage of this VM."""

from __future__ import annotations

import argparse

from gpuboard_agent.cli._common import add_config_argument, not_implemented


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(prog="vm-status", description="Show VM status.")
    parser.add_argument("--json", action="store_true", help="print the raw snapshot")
    add_config_argument(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``vm-status``."""
    build_parser().parse_args(argv)
    return not_implemented("vm-status")  # TODO(phase 1)
