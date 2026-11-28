import asyncio
import logging
import os
import secrets
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx2
import uvicorn

from verstehen.cli import (
    VerstehenServer,
    bind_listener,
    configure_logging,
    uvicorn_config,
)
from verstehen.config import TOKEN_COOKIE, Settings, load_settings
from verstehen.jobs.workers.headless import DemoRunner

PREFERRED_PORT = 28420
START_TIMEOUT_SECONDS = 30
STOP_TIMEOUT_SECONDS = 10
REPOSITORY_SPA_DIR = Path(__file__).resolve().parents[4] / "app" / "build"


class ServerStartupError(Exception):
    """The API server did not become healthy; the message says why."""


def spa_directory() -> Path:
    """The built app: VERSTEHEN_SPA_DIR, else the repository's app/build."""
    return Path(os.environ.get("VERSTEHEN_SPA_DIR", REPOSITORY_SPA_DIR))


def bind_loopback_listener() -> socket.socket:
    """Bind the preferred port so the page origin stays stable, or any free port."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        try:
            bind_listener(listener, "127.0.0.1", PREFERRED_PORT)
        except OSError:
            bind_listener(listener, "127.0.0.1", 0)
    except OSError:
        listener.close()
        raise
    return listener


class DesktopServer:
    """The API server on a background thread for the desktop window; it owns its listener."""

    def __init__(
        self, on_exit: Callable[[], None], demo_runner: DemoRunner | None = None
    ) -> None:
        self.token = secrets.token_hex(32)
        self.port = 0
        self.settings: Settings | None = None
        self._on_exit = on_exit
        self._demo_runner = demo_runner
        self._lock = threading.Lock()
        self._stopped = False
        self._listener: socket.socket | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._failure: str | None = None

    def start(self) -> None:
        """Bind a listener, configure logging, and start serving on a thread."""
        with self._lock:
            if self._stopped:
                return
        listener: socket.socket | None = None
        try:
            listener = bind_loopback_listener()
            port = listener.getsockname()[1]
            settings = load_settings(
                host="127.0.0.1",
                port=port,
                desktop_token=self.token,
                spa_dir=spa_directory(),
            )
            configure_logging(settings)
            logging.getLogger(__name__).info(
                "Starting mode=desktop data_dir=%s port=%s",
                settings.data_dir,
                port,
            )
            server = VerstehenServer(uvicorn_config(settings, self._demo_runner))
        except (ValueError, OSError, RuntimeError, ImportError) as error:
            if listener is not None:
                listener.close()
            raise ServerStartupError(str(error)) from error
        with self._lock:
            if self._stopped:
                listener.close()
                return
            self._listener = listener
            self.port = port
            self.settings = settings
            self._server = server
            self._thread = threading.Thread(target=self._serve, daemon=True)
            self._thread.start()

    def _serve(self) -> None:
        with self._lock:
            server, listener = self._server, self._listener
        assert server is not None and listener is not None
        try:
            asyncio.run(server.serve(sockets=[listener]))
            if not server.started:
                self._failure = "the server stopped before it was ready"
        except Exception as error:
            logging.getLogger(__name__).exception("The API server failed")
            self._failure = str(error) or type(error).__name__
        finally:
            self._on_exit()

    def wait_until_healthy(self, timeout: float = START_TIMEOUT_SECONDS) -> None:
        """Poll /api/health with the token until it answers 200, the server dies, or time runs out."""
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{self.port}/api/health"
        with httpx2.Client(timeout=1, trust_env=False) as client:
            while time.monotonic() < deadline:
                with self._lock:
                    if self._stopped:
                        return
                    thread = self._thread
                if thread is None or not thread.is_alive():
                    raise ServerStartupError(self._failure or "the server stopped")
                try:
                    response = client.get(
                        url, headers={"cookie": f"{TOKEN_COOKIE}={self.token}"}
                    )
                    if response.status_code == 200:
                        return
                except httpx2.HTTPError:
                    pass
                time.sleep(0.1)
        raise ServerStartupError(f"it took longer than {timeout:g} seconds")

    def stop(self) -> None:
        """Ask uvicorn to shut down and wait for its thread; safe to call twice."""
        with self._lock:
            self._stopped = True
            server, thread = self._server, self._thread
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(STOP_TIMEOUT_SECONDS)
        self.close_listener()

    def close_listener(self) -> None:
        with self._lock:
            listener, self._listener = self._listener, None
        if listener is not None:
            listener.close()
