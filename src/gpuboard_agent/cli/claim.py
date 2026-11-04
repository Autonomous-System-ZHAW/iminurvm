"""``vm-claim``: claim this VM."""

from __future__ import annotations

import argparse

from gpuboard_agent.cli._common import add_config_argument, not_implemented


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
    build_parser().parse_args(argv)
    return not_implemented("vm-claim")  # TODO(phase 2)
