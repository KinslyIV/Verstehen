import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

from verstehen.api.access import authenticate_server_request, request_refusal
from verstehen.api.auth import PairingCodeManager
from verstehen.api.auth import router as auth_router
from verstehen.api.chatgpt import router as chatgpt_router
from verstehen.api.claude_code import router as claude_code_router
from verstehen.api.graph import router as graph_router
from verstehen.api.health import router
from verstehen.api.images import router as images_router
from verstehen.api.jobs import router as jobs_router
from verstehen.api.providers import router as providers_router
from verstehen.api.sessions import router as sessions_router
from verstehen.api.side_chats import router as side_chats_router
from verstehen.api.sync import router as sync_router
from verstehen.api.sync_status import router as sync_status_router
from verstehen.api.tools import router as tools_router
from verstehen.config import Settings
from verstehen.graph.errors import GraphRefused
from verstehen.graph.extraction_service import ExtractionService
from verstehen.graph.service import GraphService
from verstehen.jobs.runner import JobRunner
from verstehen.jobs.workers.admission import WorkerAdmission
from verstehen.jobs.workers.browser import BrowserDownloadService
from verstehen.providers.accounts import AccountAdapter, AccountsService
from verstehen.providers.chatgpt.adapter import ChatGPTAccountAdapter
from verstehen.providers.chatgpt.sign_in import ChatGPTSignInService
from verstehen.providers.claude_code.adapter import ClaudeCodeAccountAdapter
from verstehen.providers.credentials import CredentialsStore
from verstehen.providers.fake import FakeAccountAdapter
from verstehen.providers.policy import ProviderPolicy
from verstehen.providers.resolve import ResolverService
from verstehen.providers.search_keys import SearchKeysService
from verstehen.providers.service import ProviderService
from verstehen.session.events import Notification, Notifications
from verstehen.session.jobs import JobService
from verstehen.session.runtime import RuntimeRegistry
from verstehen.session.sessions import SessionService
from verstehen.session.titles import TitleService
from verstehen.session.turns import TurnService
from verstehen.sidechat.service import SideChatService
from verstehen.store.artifact_views import ArtifactViewsStore
from verstehen.store.database import open_database
from verstehen.store.devices import DevicesStore
from verstehen.store.entries import EntriesStore
from verstehen.store.graph import GraphStore
from verstehen.store.jobs import JobsStore
from verstehen.store.migrate import migrate
from verstehen.store.sessions import SessionsStore
from verstehen.store.settings import SettingsStore
from verstehen.store.side_chats import SideChatsStore
from verstehen.store.sync import SyncStore
from verstehen.store.usage import UsageStore
from verstehen.sync.service import SyncService


def create_app(settings: Settings) -> FastAPI:
    """Build the API with database lifecycle, access checks, and desktop CORS."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Keep a migrated database available to routes for the application lifetime."""
        async with open_database(settings.data_dir / "verstehen.db") as database:
            await migrate(database)
            app.state.database = database
            app.state.data_dir = settings.data_dir
            app.state.devices_store = DevicesStore(database)
            runtimes = RuntimeRegistry()
            app.state.runtimes = runtimes
            sessions_store = SessionsStore(database)
            entries_store = EntriesStore(database)
            settings_store = SettingsStore(database)
            notifications = Notifications()
            app.state.notifications = notifications
            sync_store = SyncStore(database)
            app.state.sync_store = sync_store
            prompt_lock = asyncio.Lock()
            app.state.prompt_lock = prompt_lock
            claude_code_adapter = ClaudeCodeAccountAdapter(settings.provider_events)
            credentials_store = CredentialsStore(settings.data_dir)
            chatgpt_adapter = ChatGPTAccountAdapter(credentials_store)
            browser_download_service = BrowserDownloadService(settings.data_dir)
            app.state.browser_download_service = browser_download_service
            chatgpt_sign_in_service = ChatGPTSignInService(chatgpt_adapter)
            app.state.claude_code_adapter = claude_code_adapter
            app.state.chatgpt_sign_in_service = chatgpt_sign_in_service
            adapters: list[AccountAdapter] = (
                [FakeAccountAdapter(settings.fake_model_script)]
                if settings.fake_model_script
                else [chatgpt_adapter, claude_code_adapter]
            )
            accounts_service = AccountsService(adapters)
            resolver_service = ResolverService(settings_store, accounts_service)
            app.state.search_keys_service = SearchKeysService(
                credentials_store, settings_store, accounts_service
            )
            provider_policy = ProviderPolicy(settings_store)
            usage_store = UsageStore(database)
            title_service = TitleService(
                resolver_service,
                provider_policy,
                usage_store,
                sessions_store,
                notifications,
                settings.provider_events,
            )
            app.state.provider_service = ProviderService(
                settings_store, accounts_service, resolver_service
            )
            jobs_store = JobsStore(database)

            async def wake_session(session_id: str) -> None:
                await turn_service.pump_deliveries(session_id)

            def jobs_changed(session_id: str) -> None:
                notifications.publish(
                    Notification(type="jobs-changed", session_id=session_id)
                )

            job_runner = JobRunner(
                jobs_store,
                settings_store,
                resolver_service,
                provider_policy,
                usage_store,
                credentials_store,
                WorkerAdmission(settings_store),
                settings.data_dir,
                wake_session,
                jobs_changed,
                settings.provider_events,
            )

            async def before_side_ask(session_id: str) -> None:
                if task := runtimes.get(session_id).compaction:
                    await asyncio.shield(task)

            def side_chats_changed(session_id: str) -> None:
                notifications.publish(
                    Notification(type="side-chats-changed", session_id=session_id)
                )

            side_chat_service = SideChatService(
                sessions_store,
                entries_store,
                SideChatsStore(database),
                settings_store,
                resolver_service,
                provider_policy,
                settings.data_dir,
                before_side_ask,
                side_chats_changed,
                lambda session_id: runtimes.get(session_id).lock,
                settings.provider_events,
            )

            def graph_changed(revision: int) -> None:
                notifications.publish(
                    Notification(type="graph-changed", revision=revision)
                )

            graph_store = GraphStore(database, graph_changed)

            def extractions_changed() -> None:
                notifications.publish(Notification(type="extractions-changed"))

            extraction_service = ExtractionService(
                graph_store,
                sessions_store,
                entries_store,
                settings_store,
                resolver_service,
                provider_policy,
                usage_store,
                job_runner.admission.request,
                extractions_changed,
                settings.provider_events,
            )
            app.state.extraction_service = extraction_service
            app.state.side_chat_service = side_chat_service
            app.state.session_service = SessionService(
                sessions_store,
                entries_store,
                runtimes,
                notifications,
                resolver_service,
                jobs_store,
                ArtifactViewsStore(database),
                settings.data_dir,
                extraction_service,
                graph_store,
                side_chat_service,
            )

            async def check_graph_session(session_id: str) -> None:
                if runtimes.get(session_id).run is not None:
                    raise GraphRefused(
                        "A turn is running in this session — try again when it finishes",
                        409,
                        "turn_in_flight",
                    )
                if await jobs_store.running(session_id):
                    raise GraphRefused(
                        "Background jobs are still running in this session — try again when they finish",
                        409,
                        "jobs_running",
                    )

            async def delete_graph_session(session_id: str) -> None:
                result = await app.state.session_service.delete(
                    session_id, "delete-nodes"
                )
                if result is not None:
                    raise GraphRefused(
                        result.reason.get("error", "Could not delete session"),
                        result.status,
                        result.reason.get("code"),
                    )

            app.state.graph_service = GraphService(
                graph_store,
                sessions_store,
                settings_store,
                usage_store,
                extraction_service,
                delete_graph_session,
                check_graph_session,
            )
            app.state.turn_service = turn_service = TurnService(
                sessions_store,
                entries_store,
                settings_store,
                settings.data_dir,
                resolver_service,
                provider_policy,
                usage_store,
                title_service,
                runtimes,
                notifications,
                jobs_store,
                job_runner,
                side_chat_service.snapshot,
                extraction_service,
                graph_store,
                settings.provider_events,
            )

            app.state.job_service = JobService(
                sessions_store,
                jobs_store,
                job_runner,
                runtimes,
                turn_service.delivery_service,
            )
            sync_service = SyncService(
                sync_store,
                credentials_store,
                runtimes,
                notifications,
                settings.data_dir,
                prompt_lock=prompt_lock,
            )
            app.state.sync_service = sync_service
            if settings.server:
                database.on_sync_write = lambda: notifications.publish(
                    Notification(type="sync-changed")
                )
            else:
                database.on_sync_write = sync_service.notify_local_change
                sync_service.start()
            turn_service.delivery_service.start_watching()
            try:
                yield
            finally:
                await sync_service.close()
                await turn_service.delivery_service.close()
                await extraction_service.close()
                await side_chat_service.close()
                await job_runner.close()
                await browser_download_service.close()
                await runtimes.close()
                await title_service.close()
                claude_code_adapter.close()
                await chatgpt_sign_in_service.close()
                await chatgpt_adapter.close()

    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    app.state.pairing_code_manager = PairingCodeManager()

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        message = next(
            (
                issue["msg"]
                for issue in error.errors()
                if issue["type"] == "file_access_policy"
            ),
            "Invalid request body",
        )
        return JSONResponse({"error": message}, status_code=400)

    @app.middleware("http")
    async def access(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Reject API requests that fail the launch mode’s access policy."""
        path = request.url.path
        if path == "/api" or path.startswith("/api/"):
            if settings.server:
                denied = await authenticate_server_request(
                    request, request.app.state.devices_store
                )
                if denied is not None:
                    return denied
                if path == "/api/sync/now":
                    return JSONResponse(
                        {"error": "Sync client is not enabled in server mode."},
                        status_code=404,
                    )
            else:
                refusal = request_refusal(request, settings)
                if refusal:
                    return JSONResponse(
                        {"error": refusal},
                        status_code=403,
                        headers={"Cache-Control": "no-store"},
                    )
                if (
                    path == "/api/auth"
                    or path.startswith("/api/auth/")
                    or path in ("/api/sync/push", "/api/sync/pull")
                    or path.startswith("/api/sync/images/")
                ):
                    return JSONResponse(
                        {"error": "Server mode is not enabled."},
                        status_code=404,
                    )
        return await call_next(request)

    if settings.desktop:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["tauri://localhost", "http://tauri.localhost"],
            allow_methods=["*"],
            allow_headers=["x-verstehen-token", "content-type"],
        )
    elif settings.server:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "tauri://localhost",
                "http://tauri.localhost",
                "https://tauri.localhost",
            ],
            allow_methods=["*"],
            allow_headers=["authorization", "x-verstehen-token", "content-type"],
        )

    app.include_router(auth_router)
    app.include_router(sync_router)
    app.include_router(sync_status_router)
    app.include_router(graph_router)
    app.include_router(tools_router)
    app.include_router(router)
    app.include_router(sessions_router)
    app.include_router(images_router)
    app.include_router(jobs_router)
    app.include_router(side_chats_router)
    app.include_router(providers_router)
    app.include_router(claude_code_router)
    app.include_router(chatgpt_router)
    return app
