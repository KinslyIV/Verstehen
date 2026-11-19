from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse, Response

from verstehen.api.sessions import ApiError
from verstehen.providers.accounts import Account, AccountUnavailable
from verstehen.providers.chatgpt.sign_in import (
    ChatGPTSignInService,
    SignInBusy,
    SignInStarted,
    SignInStatus,
)


def get_chatgpt_sign_in_service(request: Request) -> ChatGPTSignInService:
    return request.app.state.chatgpt_sign_in_service


ChatGPTSignInServiceDependency = Annotated[
    ChatGPTSignInService, Depends(get_chatgpt_sign_in_service)
]
router = APIRouter(responses={404: {"model": ApiError}, 409: {"model": ApiError}})


@router.get("/api/accounts/chatgpt", response_model=list[Account])
async def list_accounts(service: ChatGPTSignInServiceDependency):
    return await service.adapter.accounts()


@router.post("/api/accounts/chatgpt", response_model=SignInStarted)
async def start_sign_in(service: ChatGPTSignInServiceDependency):
    try:
        started = await service.start()
        return JSONResponse(started.model_dump(), headers={"Cache-Control": "no-store"})
    except SignInBusy as error:
        return JSONResponse({"error": str(error)}, status_code=409)


@router.get("/api/accounts/chatgpt/sign-in/{sign_in_id}", response_model=SignInStatus)
async def sign_in_status(sign_in_id: str, service: ChatGPTSignInServiceDependency):
    status = service.get_status(sign_in_id)
    if status is None:
        return JSONResponse({"error": "Sign-in not found"}, status_code=404)
    return status


@router.post("/api/accounts/chatgpt/{account_id}/sign-in", response_model=SignInStarted)
async def sign_in_again(account_id: str, service: ChatGPTSignInServiceDependency):
    try:
        started = await service.start(account_id)
        return JSONResponse(started.model_dump(), headers={"Cache-Control": "no-store"})
    except AccountUnavailable as error:
        return JSONResponse({"error": error.reason}, status_code=404)
    except SignInBusy as error:
        return JSONResponse({"error": str(error)}, status_code=409)


@router.delete("/api/accounts/chatgpt/{account_id}", status_code=204)
async def remove_account(account_id: str, service: ChatGPTSignInServiceDependency):
    try:
        await service.remove(account_id)
        return Response(status_code=204)
    except AccountUnavailable as error:
        return JSONResponse({"error": error.reason}, status_code=404)
