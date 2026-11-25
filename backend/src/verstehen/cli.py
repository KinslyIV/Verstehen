import argparse
import asyncio
import json
import logging
import os
import socket
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from verstehen.app import create_app
from verstehen.config import Settings, load_settings, resolve_data_dir
from verstehen.store.database import open_database
from verstehen.store.devices import DevicesStore
from verstehen.store.migrate import migrate


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
    """An API server that announces its listening port on stdout."""

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        """Start listening, then emit the one-line JSON port handshake."""
        await super().startup(sockets=sockets)
        if self.started and sockets:
            port = sockets[0].getsockname()[1]
            logging.getLogger(__name__).info(
                "Listening on %s:%s", self.config.host, port
            )
            print(json.dumps({"port": port}), flush=True)


GRACEFUL_SHUTDOWN_SECONDS = 5


def bind_listener(listener: socket.socket, host: str, port: int) -> None:
    """Bind so a restart is not blocked by TIME_WAIT sockets left on the port."""
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))


def uvicorn_config(settings: Settings) -> uvicorn.Config:
    """Configure uvicorn for the application; the caller supplies the listening socket."""
    return uvicorn.Config(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,
        proxy_headers=False,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )


async def serve(settings: Settings) -> None:
    """Run the API server until it is told to exit."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        bind_listener(listener, settings.host, settings.port)
        server = SidecarServer(uvicorn_config(settings))
        await server.serve(sockets=[listener])
        if not server.started:
            raise RuntimeError("The sidecar failed to start; see verstehen.log.")


async def mint_device_token(device_name: str, data_dir: Path) -> dict[str, str]:
    """Migrate the database, create a device record, and return its id and token."""
    cleaned = device_name.strip()
    if not cleaned:
        raise ValueError("Device name must not be empty.")
    data_dir.mkdir(parents=True, exist_ok=True)
    async with open_database(data_dir / "verstehen.db") as database:
        await migrate(database)
        device, token = await DevicesStore(database).create(cleaned)
    return {"device_id": device.id, "token": token}


def main() -> None:
    """Load launch settings and run the sidecar or CLI subcommand."""
    os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--host")
    parser.add_argument("--port")
    commands = parser.add_subparsers(dest="command")
    importing = commands.add_parser(
        "import-learnharness",
        help="replace all sessions and the graph with a LearnHarness data folder",
    )
    importing.add_argument("folder", type=Path)
    importing.add_argument("--dry-run", action="store_true")
    minting = commands.add_parser(
        "mint-token",
        help="create a paired device and print its bearer token once",
    )
    minting.add_argument("device_name")
    commands.add_parser("desktop", help="open the desktop window")
    arguments = parser.parse_args()
    if arguments.self_check:
        from verstehen.self_check import run_self_check

        raise SystemExit(0 if run_self_check() else 1)
    if arguments.command == "import-learnharness":
        from verstehen.lh_import.run import import_learnharness

        try:
            settings = load_settings(create_data_dir=False)
        except (ValueError, OSError) as error:
            print(str(error), file=sys.stderr)
            raise SystemExit(1) from None
        raise SystemExit(
            import_learnharness(arguments.folder, settings, dry_run=arguments.dry_run)
        )
    if arguments.command == "desktop":
        from verstehen.desktop.shell import run_desktop

        raise SystemExit(run_desktop())
    if arguments.command == "mint-token":
        try:
            if not arguments.device_name.strip():
                raise ValueError("Device name must not be empty.")
            payload = asyncio.run(
                mint_device_token(arguments.device_name, resolve_data_dir())
            )
            print(json.dumps(payload), flush=True)
        except (ValueError, OSError) as error:
            print(str(error), file=sys.stderr)
            raise SystemExit(1) from None
        raise SystemExit(0)
    try:
        settings = load_settings(
            server=arguments.server,
            host=arguments.host,
            port=arguments.port,
        )
        configure_logging(settings)
        mode = "server" if settings.server else "browser-only"
        logging.getLogger(__name__).info(
            "Starting mode=%s data_dir=%s host=%s port=%s",
            mode,
            settings.data_dir,
            settings.host,
            settings.port,
        )
        asyncio.run(serve(settings))
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        logging.shutdown()
