"""Helpers shared by the CLI commands."""

from __future__ import annotations

import argparse
import getpass
import sys

EXIT_NOT_IMPLEMENTED = 70


def current_user() -> str:
    """Return the invoking Linux user name."""
    return getpass.getuser()


def parse_duration(text: str) -> float:
    """Parse ``90m``, ``4h`` or ``1d`` into hours."""
    raise NotImplementedError  # TODO(phase 2)


def add_config_argument(parser: argparse.ArgumentParser) -> None:
    """Add the common ``--config`` option."""
    parser.add_argument("--config", help="path to agent.yaml")


def not_implemented(command: str) -> int:
    """Placeholder body for stubbed commands."""
    print(f"{command}: not implemented yet", file=sys.stderr)
    return EXIT_NOT_IMPLEMENTED
