from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from verstehen.providers.credentials import SearchKeyEngine
from verstehen.providers.search_keys import SearchKeysService, SearchKeysStatus

router = APIRouter()


def get_search_keys_service(request: Request) -> SearchKeysService:
    return request.app.state.search_keys_service


SearchKeysDependency = Annotated[SearchKeysService, Depends(get_search_keys_service)]


class SearchKeyBody(BaseModel):
    value: str = Field(repr=False)


@router.get("/api/search-keys", response_model=SearchKeysStatus)
async def get_search_keys(service: SearchKeysDependency) -> SearchKeysStatus:
    return await service.status()


@router.put("/api/search-keys/{engine}", response_model=SearchKeysStatus)
async def put_search_key(
    engine: SearchKeyEngine, body: SearchKeyBody, service: SearchKeysDependency
):
    try:
        return await service.set_key(engine, body.value)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)


@router.delete("/api/search-keys/{engine}", response_model=SearchKeysStatus)
async def delete_search_key(engine: SearchKeyEngine, service: SearchKeysDependency):
    try:
        return await service.set_key(engine, None)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
