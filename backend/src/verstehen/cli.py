import argparse
import asyncio
import json
import logging
import socket
import sys
import threading
from logging.handlers import RotatingFileHandler

import uvicorn

from verstehen.app import create_app
from verstehen.config import Settings, load_settings


def configure_logging(settings: Settings) -> None:
    """Send application and server logs to a rotating file in the data directory."""
    directory = settings.data_dir / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "verstehen.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


class SidecarServer(uvicorn.Server):
    """A loopback API server that announces its listening port on stdout."""

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        """Start listening, then emit the one-line JSON port handshake."""
        await super().startup(sockets=sockets)
        if self.started and sockets:
            port = sockets[0].getsockname()[1]
            logging.getLogger(__name__).info("Listening on 127.0.0.1:%s", port)
            print(json.dumps({"port": port}), flush=True)


async def serve(settings: Settings) -> None:
    """Run the loopback sidecar, shutting down on desktop stdin EOF."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", settings.port))
        config = uvicorn.Config(
            create_app(settings),
            host="127.0.0.1",
            port=settings.port,
            log_config=None,
            proxy_headers=False,
        )
        server = SidecarServer(config)
        if settings.desktop:
            loop = asyncio.get_running_loop()

            def watch_stdin() -> None:
                """Request server shutdown when the desktop parent closes stdin."""
                while sys.stdin.buffer.read(4096):
                    pass
                loop.call_soon_threadsafe(setattr, server, "should_exit", True)

            threading.Thread(target=watch_stdin, daemon=True).start()
        await server.serve(sockets=[listener])
        if not server.started:
            raise RuntimeError("The sidecar failed to start; see verstehen.log.")


def main() -> None:
    """Load launch settings and run the sidecar with file logging."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    if parser.parse_args().self_check:
        from verstehen.self_check import run_self_check

        raise SystemExit(0 if run_self_check() else 1)
    try:
        settings = load_settings()
        configure_logging(settings)
        logging.getLogger(__name__).info(
            "Starting mode=%s data_dir=%s port=%s",
            "desktop" if settings.desktop else "browser-only",
            settings.data_dir,
            settings.port,
        )
        asyncio.run(serve(settings))
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        logging.shutdown()
