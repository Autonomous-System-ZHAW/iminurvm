"""``gpu-board-collector`` entry point."""

from __future__ import annotations

import argparse
import logging
import threading
import time
from pathlib import Path

from proxmoxer.core import ResourceException

from gpuboard_collector.config import CollectorConfig, load_collector_config
from gpuboard_collector.merge import merge, write_status
from gpuboard_collector.proxmox import fetch_inventory
from gpuboard_collector.ssh_pull import pull_all
from gpuboard_collector.web import BoardStore, make_server
from gpuboard_common.models import BoardState
from gpuboard_common.timeutil import now

logger = logging.getLogger(__name__)


def _poll(config: CollectorConfig) -> BoardState:
    inventory = fetch_inventory(config)
    results = pull_all(config, inventory)
    board = merge(inventory, results, now())
    write_status(board, config.status_path)
    return board


def poll_once(config_path: str | None = None) -> BoardState:
    """One cycle: inventory -> pull -> merge -> write ``status.json``."""
    config = load_collector_config(
        Path(config_path) if config_path is not None else None
    )
    return _poll(config)


def poll_forever(
    config: CollectorConfig,
    config_path: Path | None = None,
    store: BoardStore | None = None,
) -> None:
    """Poll immediately, then wait between cycles and retry recoverable failures.

    Reload configuration after each wait. If reloading fails, skip the cycle
    and retry after the last successfully loaded interval.
    """
    while True:
        try:
            board = _poll(config)
        except (OSError, ValueError, RuntimeError, ResourceException) as exc:
            logger.error("Collector cycle failed: %s", exc)
        else:
            if store is not None:
                store.set_board(board)
            logger.info("Collector cycle completed: %d VM(s)", len(board.vms))
            for entry in board.vms:
                if entry.error is not None:
                    logger.warning("VM %s: %s", entry.inventory.vmid, entry.error)

        while True:
            time.sleep(config.poll_interval_seconds)
            try:
                updated = load_collector_config(config_path)
            except (OSError, ValueError) as exc:
                logger.error("Collector configuration reload failed: %s", exc)
            else:
                if (updated.listen_host, updated.listen_port) != (
                    config.listen_host,
                    config.listen_port,
                ):
                    logger.warning("HTTP listener changes require a service restart")
                config = updated
                if store is not None:
                    store.set_interval(config.poll_interval_seconds)
                break


def main(argv: list[str] | None = None) -> int:
    """Run the polling loop and read-only status endpoint."""
    parser = argparse.ArgumentParser(prog="gpu-board-collector", description=__doc__)
    parser.add_argument("--config", type=Path, help="path to collector.yaml")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        config = load_collector_config(args.config)
    except (OSError, ValueError) as exc:
        logger.error("Collector configuration failed: %s", exc)
        return 1
    store = BoardStore(config.poll_interval_seconds)
    try:
        server = make_server(config.listen_host, config.listen_port, store)
    except OSError as exc:
        logger.error("HTTP listener failed: %s", exc)
        return 1
    thread = threading.Thread(target=server.serve_forever, name="status-http")
    thread.start()
    logger.info("HTTP status listener started on %s:%d", *server.server_address[:2])
    try:
        poll_forever(config, args.config, store)
    except KeyboardInterrupt:
        logger.info("Collector stopped")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    return 0
