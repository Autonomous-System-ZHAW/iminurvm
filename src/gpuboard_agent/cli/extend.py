"""``vm-extend``: push the end of the current claim."""

from __future__ import annotations

import argparse

from gpuboard_agent.cli._common import add_config_argument, not_implemented


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(prog="vm-extend", description="Extend a claim.")
    parser.add_argument("duration", help="e.g. 2h")
    add_config_argument(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``vm-extend``."""
    build_parser().parse_args(argv)
    return not_implemented("vm-extend")  # TODO(phase 2)
