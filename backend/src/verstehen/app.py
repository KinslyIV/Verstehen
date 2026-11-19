from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

from verstehen.api.access import request_refusal
from verstehen.api.health import router
from verstehen.config import Settings
from verstehen.store.database import open_database
from verstehen.store.migrate import migrate


def create_app(settings: Settings) -> FastAPI:
    """Build the API with database lifecycle, access checks, and desktop CORS."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Keep a migrated database available to routes for the application lifetime."""
        async with open_database(settings.data_dir / "verstehen.db") as database:
            await migrate(database)
            app.state.database = database
            yield

    app = FastAPI(lifespan=lifespan)

    @app.middleware("http")
    async def access(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Reject API requests that fail the launch mode’s access policy."""
        if request.url.path == "/api" or request.url.path.startswith("/api/"):
            refusal = request_refusal(request, settings)
            if refusal:
                return JSONResponse(
                    {"error": refusal},
                    status_code=403,
                    headers={"Cache-Control": "no-store"},
                )
        return await call_next(request)

    if settings.desktop:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["tauri://localhost", "http://tauri.localhost"],
            allow_methods=["*"],
            allow_headers=["x-verstehen-token", "content-type"],
        )

    app.include_router(router)
    return app
