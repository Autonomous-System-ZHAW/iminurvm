"""Read-only HTTP dashboard and status endpoint."""

from __future__ import annotations

import json
import logging
import secrets
import threading
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Any

from jinja2 import (
    Environment,
    PackageLoader,
    Template,
    TemplateError,
    select_autoescape,
)

from gpuboard_collector.freshness import assess_board
from gpuboard_common.models import BoardState
from gpuboard_common.serialize import BOARD_SCHEMA_VERSION, board_to_dict
from gpuboard_common.timeutil import now

logger = logging.getLogger(__name__)

_ICONS = {
    "/favicon.ico": ("gpu-claim-favicon.ico", "image/x-icon"),
    "/static/gpu-claim-favicon.ico": ("gpu-claim-favicon.ico", "image/x-icon"),
    "/static/gpu-claim-favicon-32.png": ("gpu-claim-favicon-32.png", "image/png"),
    "/static/gpu-claim-favicon-512.png": ("gpu-claim-favicon-512.png", "image/png"),
    "/static/gpu-claim-apple-touch-icon.png": (
        "gpu-claim-apple-touch-icon.png",
        "image/png",
    ),
}


@lru_cache(maxsize=1)
def _dashboard_template() -> Template:
    environment = Environment(
        loader=PackageLoader("gpuboard_collector", "templates"),
        autoescape=select_autoescape(default=True),
    )
    return environment.get_template("dashboard.html.j2")


def render_dashboard(board: dict[str, Any], nonce: str = "") -> str:
    """Render a read-only board from the same observation as the JSON endpoint."""
    return _dashboard_template().render(board=board, nonce=nonce)


class BoardStore:
    """Share the last successfully written board and current interval safely."""

    def __init__(self, poll_interval_seconds: float) -> None:
        self._lock = threading.Lock()
        self._board: BoardState | None = None
        self._interval = poll_interval_seconds

    def set_board(self, board: BoardState) -> None:
        """Publish a successfully written board."""
        with self._lock:
            self._board = board

    def set_interval(self, interval: float) -> None:
        """Use the last successfully loaded polling interval for freshness."""
        with self._lock:
            self._interval = interval

    def read(self) -> tuple[BoardState | None, float]:
        """Return a consistent board and interval pair."""
        with self._lock:
            return self._board, self._interval


def status_response(store: BoardStore) -> tuple[HTTPStatus, dict[str, Any]]:
    """Build a status response with freshness assessed at request time."""
    board, interval = store.read()
    assessed_at = now()
    freshness = assess_board(board, assessed_at, interval)
    if board is None:
        data: dict[str, Any] = {
            "schema_version": BOARD_SCHEMA_VERSION,
            "generated_at": None,
            "vms": [],
        }
        code = HTTPStatus.SERVICE_UNAVAILABLE
    else:
        data = board_to_dict(board)
        for entry in data["vms"]:
            entry["snapshot_freshness"] = freshness.snapshots[
                entry["inventory"]["vmid"]
            ].value
        code = HTTPStatus.OK
    data["freshness"] = freshness.board.value
    data["assessed_at"] = assessed_at.isoformat()
    data["poll_interval_seconds"] = interval
    return code, data


def make_server(host: str, port: int, store: BoardStore) -> ThreadingHTTPServer:
    """Bind the HTTP listener; caller owns its lifecycle."""

    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(10)

        def do_GET(self) -> None:
            if self.path in _ICONS:
                filename, content_type = _ICONS[self.path]
                try:
                    body = (
                        files("gpuboard_collector")
                        .joinpath("static", filename)
                        .read_bytes()
                    )
                except OSError:
                    logger.exception("Failed to load dashboard icon %s", filename)
                    self._send(
                        HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "icon error"}
                    )
                    return
                self._send_body(HTTPStatus.OK, body, content_type)
                return
            if self.path not in ("/", "/status.json"):
                self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                code, data = status_response(store)
                if self.path == "/":
                    nonce = secrets.token_urlsafe(16)
                    self._send_body(
                        code,
                        render_dashboard(data, nonce).encode("utf-8"),
                        "text/html",
                        nonce,
                    )
                else:
                    self._send(code, data)
            except (ValueError, TypeError, OverflowError, TemplateError):
                logger.exception("Failed to render status response")
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "status error"})

        def _send(self, code: HTTPStatus, data: dict[str, Any]) -> None:
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self._send_body(code, body, "application/json")

        def _send_body(
            self,
            code: HTTPStatus,
            body: bytes,
            content_type: str,
            script_nonce: str | None = None,
        ) -> None:
            script_src = f"script-src 'nonce-{script_nonce}'; " if script_nonce else ""
            self.send_response(code)
            if content_type in ("text/html", "application/json"):
                content_type = f"{content_type}; charset=utf-8"
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                f"default-src 'none'; {script_src}style-src 'unsafe-inline'; "
                "img-src 'self'; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            logger.info("HTTP %s: %s", self.address_string(), format % args)

    return ThreadingHTTPServer((host, port), Handler)
