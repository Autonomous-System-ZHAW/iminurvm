"""``vm-run``: bind a claim to a process; release when it exits."""

from __future__ import annotations

import argparse

from gpuboard_agent.cli._common import add_config_argument, not_implemented


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (``vm-run [options] -- command ...``)."""
    parser = argparse.ArgumentParser(prog="vm-run", description="Run with a claim.")
    parser.add_argument("-p", "--project", default="")
    parser.add_argument("-m", "--message", default="")
    parser.add_argument("-d", "--duration", default=None, help="safety expiry")
    add_config_argument(parser)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``vm-run``."""
    build_parser().parse_args(argv)
    return not_implemented("vm-run")  # TODO(phase 2)
