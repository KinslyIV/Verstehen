from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse

from verstehen.api.sessions import ApiError, ModelUnavailable
from verstehen.providers.resolve import ResolutionError
from verstehen.providers.service import ModelCatalog, ProviderService
from verstehen.store.settings import ModelPick, Settings


def get_provider_service(request: Request) -> ProviderService:
    return request.app.state.provider_service


ProviderServiceDependency = Annotated[ProviderService, Depends(get_provider_service)]
router = APIRouter(
    responses={400: {"model": ApiError}, 503: {"model": ModelUnavailable}}
)


@router.get("/api/settings", response_model=Settings)
async def get_settings(provider_service: ProviderServiceDependency) -> Settings:
    return await provider_service.settings()


@router.put("/api/settings", response_model=Settings)
async def put_settings(body: Settings, provider_service: ProviderServiceDependency):
    try:
        return await provider_service.save_settings(body)
    except ResolutionError as error:
        return JSONResponse(error.envelope(), status_code=503)


@router.get("/api/models", response_model=ModelCatalog)
async def get_models(provider_service: ProviderServiceDependency) -> ModelCatalog:
    return await provider_service.catalog()


@router.post("/api/settings/default-model", response_model=ModelPick)
async def set_default_model(
    body: ModelPick, provider_service: ProviderServiceDependency
):
    try:
        return await provider_service.set_default(body)
    except ResolutionError as error:
        return JSONResponse(error.envelope(), status_code=503)
