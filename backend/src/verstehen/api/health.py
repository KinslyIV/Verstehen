from typing import Annotated

from fastapi import APIRouter, Depends

from verstehen.api.deps import get_database
from verstehen.store.database import Database

router = APIRouter()


@router.get("/api/health")
async def health(
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, str]:
    await database.check_health()
    return {"status": "ok"}
