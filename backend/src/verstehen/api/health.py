from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from verstehen.api.deps import get_database
from verstehen.store.database import Database
from verstehen.sync.provision import INVOCATION_HEADER, SCHEMA_HEADER

router = APIRouter()


@router.get("/api/health")
async def health(
    request: Request,
    response: Response,
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, str]:
    await database.check_health()
    invocation = request.app.state.settings.server_invocation_id
    if invocation:
        schema = await request.app.state.sync_store.schema_version()
        response.headers[INVOCATION_HEADER] = invocation
        response.headers[SCHEMA_HEADER] = str(schema)
    return {"status": "ok"}
