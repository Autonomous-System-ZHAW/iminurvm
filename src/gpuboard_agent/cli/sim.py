"""``sim-start`` / ``sim-stop``: ``docker compose`` with owner/project labels."""

from __future__ import annotations

import argparse

from gpuboard_agent.cli._common import not_implemented


def compose_env(user: str, project: str) -> dict[str, str]:
    """Environment variables that make compose files set the labels."""
    raise NotImplementedError  # TODO(phase 2)


def build_parser(prog: str) -> argparse.ArgumentParser:
    """Build the shared argument parser."""
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("-p", "--project", default="")
    parser.add_argument("compose_args", nargs=argparse.REMAINDER)
    return parser


def start_main(argv: list[str] | None = None) -> int:
    """Entry point for ``sim-start``."""
    build_parser("sim-start").parse_args(argv)
    return not_implemented("sim-start")  # TODO(phase 2)


def stop_main(argv: list[str] | None = None) -> int:
    """Entry point for ``sim-stop``."""
    build_parser("sim-stop").parse_args(argv)
    return not_implemented("sim-stop")  # TODO(phase 2)
