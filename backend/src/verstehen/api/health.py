from collections.abc import Awaitable, Callable

from fastapi import APIRouter


def health_router(check_database: Callable[[], Awaitable[None]]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/health")
    async def health() -> dict[str, str]:
        await check_database()
        return {"status": "ok"}

    return router
