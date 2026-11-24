from typing import Annotated

import httpx2
from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, Response

from verstehen.api.auth import DeviceList, PairingCodeResponse
from verstehen.api.sessions import ApiError, Ok
from verstehen.api.sync_status import (
    SyncServiceDependency,
    SyncStatusResponse,
    SyncStoreDependency,
    build_sync_status,
)
from verstehen.providers.accounts import Account
from verstehen.providers.chatgpt.sign_in import SignInStatus
from verstehen.providers.claude_code.binary import BinaryStatus
from verstehen.sync.provision import (
    HostKeyMismatchError,
    InstallBusyError,
    InstallMode,
    ServerInstallService,
    ServerInstallStatus,
    ServerOAuthBusyError,
    ServerOAuthCancelledError,
    ServerOAuthService,
    ServerProxy,
    ServerProxyError,
    ServerSignInResponse,
    SshAuthError,
    SshUnreachableError,
    trust_host_key,
    validate_host,
    validate_ssh_user,
)


def get_server_proxy(request: Request) -> ServerProxy:
    return request.app.state.server_proxy


def get_server_install_service(request: Request) -> ServerInstallService:
    return request.app.state.server_install_service


def get_server_oauth_service(request: Request) -> ServerOAuthService:
    return request.app.state.server_oauth_service


ServerProxyDependency = Annotated[ServerProxy, Depends(get_server_proxy)]
ServerInstallDependency = Annotated[
    ServerInstallService, Depends(get_server_install_service)
]
ServerOAuthDependency = Annotated[ServerOAuthService, Depends(get_server_oauth_service)]

router = APIRouter(
    responses={
        400: {"model": ApiError},
        401: {"model": ApiError},
        404: {"model": ApiError},
        409: {"model": ApiError},
        502: {"model": ApiError},
    }
)


class ServerInstallInput(BaseModel):
    host: str
    server_port: int = Field(default=8420, ge=1, le=65535)
    ssh_user: str
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_password: str | None = Field(default=None, repr=False)
    device_name: str = "Laptop"
    mode: InstallMode = "install"


class TrustHostInput(BaseModel):
    host: str
    ssh_port: int = Field(default=22, ge=1, le=65535)
    fingerprint_sha256: str


class ServerConnectInput(BaseModel):
    host: str
    server_port: int = Field(default=8420, ge=1, le=65535)
    pairing_code: str | None = Field(default=None, repr=False)
    token: str | None = Field(default=None, repr=False)
    device_name: str = "Laptop"
    ssh_user: str | None = None
    ssh_port: int | None = Field(default=None, ge=1, le=65535)


class ServerChatGPTSignInInput(BaseModel):
    account_id: str | None = None
    ssh_user: str | None = None
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    ssh_password: str | None = Field(default=None, repr=False)


def _proxy_error_response(error: ServerProxyError) -> JSONResponse:
    body: dict[str, str] = {"error": error.message}
    if error.code:
        body["code"] = error.code
    return JSONResponse(body, status_code=error.status_code)


@router.post(
    "/api/server/install",
    status_code=202,
    response_model=ServerInstallStatus,
)
async def start_server_install(
    body: ServerInstallInput,
    install_service: ServerInstallDependency,
):
    try:
        status = install_service.start(
            host=body.host,
            server_port=body.server_port,
            ssh_user=body.ssh_user,
            ssh_port=body.ssh_port,
            ssh_password=body.ssh_password,
            device_name=body.device_name,
            mode=body.mode,
        )
        return JSONResponse(status.model_dump(mode="json"), status_code=202)
    except InstallBusyError as error:
        return JSONResponse(
            {"error": str(error), "code": "install_busy"}, status_code=409
        )
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)


@router.get("/api/server/install", response_model=ServerInstallStatus)
async def get_server_install_status(
    install_service: ServerInstallDependency,
) -> ServerInstallStatus:
    return install_service.status


@router.post("/api/server/trust-host", response_model=Ok)
async def trust_server_host(
    body: TrustHostInput,
    install_service: ServerInstallDependency,
):
    try:
        await trust_host_key(
            install_service.ssh_backend,
            body.host,
            body.ssh_port,
            body.fingerprint_sha256,
            install_service.known_hosts_path,
        )
        return Ok()
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    except HostKeyMismatchError as error:
        return JSONResponse(
            {"error": str(error), "code": "host_key_mismatch"}, status_code=409
        )
    except SshUnreachableError as error:
        return JSONResponse(
            {"error": str(error), "code": "ssh_unreachable"}, status_code=502
        )


@router.post("/api/server/connect", response_model=SyncStatusResponse)
async def connect_existing_server(
    body: ServerConnectInput,
    sync_store: SyncStoreDependency,
    sync_service: SyncServiceDependency,
    proxy: ServerProxyDependency,
):
    try:
        cleaned_host = validate_host(body.host)
        cleaned_user = (
            validate_ssh_user(body.ssh_user)
            if body.ssh_user and body.ssh_user.strip()
            else None
        )
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)

    pairing_code = (body.pairing_code or "").strip()
    raw_token = (body.token or "").strip()
    if not pairing_code and not raw_token:
        return JSONResponse(
            {"error": "Provide either a pairing code or a bearer token."},
            status_code=400,
        )

    server_url = f"http://{cleaned_host}:{body.server_port}"
    device_name = body.device_name.strip() or "Laptop"
    resolved_token: str
    resolved_device_id: str | None = None

    try:
        async with proxy.client_factory() as client:
            if pairing_code:
                resp = await client.post(
                    f"{server_url}/api/auth/pair",
                    json={"code": pairing_code, "device_name": device_name},
                    timeout=10.0,
                )
                if resp.status_code >= 400:
                    payload = (
                        resp.json()
                        if resp.headers.get("content-type", "").startswith(
                            "application/json"
                        )
                        else {}
                    )
                    return JSONResponse(
                        {
                            "error": payload.get(
                                "error", "Failed to pair with sync server."
                            )
                        },
                        status_code=resp.status_code,
                    )
                paired = resp.json()
                resolved_token = str(paired["token"])
                resolved_device_id = str(paired["device_id"])
            else:
                resp = await client.get(
                    f"{server_url}/api/auth/devices",
                    headers={"Authorization": f"Bearer {raw_token}"},
                    timeout=10.0,
                )
                if resp.status_code == 401:
                    return JSONResponse(
                        {
                            "error": "Server rejected the bearer token.",
                            "code": "server_unauthorized",
                        },
                        status_code=401,
                    )
                if resp.status_code >= 400:
                    return JSONResponse(
                        {"error": f"Server returned HTTP {resp.status_code}."},
                        status_code=resp.status_code,
                    )
                resolved_token = raw_token
                resolved_device_id = resp.json().get("current_device_id") or None
    except (httpx2.HTTPError, OSError, TimeoutError) as error:
        return JSONResponse(
            {
                "error": f"Could not reach sync server at {server_url}: {error}",
                "code": "server_unreachable",
            },
            status_code=502,
        )

    await sync_service.configure(
        server_url,
        resolved_token,
        ssh_user=cleaned_user,
        ssh_port=body.ssh_port,
        server_device_id=resolved_device_id,
    )
    return await build_sync_status(sync_store, sync_service)


@router.post("/api/server/disconnect", response_model=SyncStatusResponse)
async def disconnect_server(
    sync_store: SyncStoreDependency,
    sync_service: SyncServiceDependency,
    oauth_service: ServerOAuthDependency,
) -> SyncStatusResponse:
    await oauth_service.cancel()
    await sync_service.disconnect()
    return await build_sync_status(sync_store, sync_service)


@router.get("/api/server/accounts/claude-code", response_model=BinaryStatus)
async def get_server_claude_code(proxy: ServerProxyDependency):
    try:
        return await proxy.get_claude_code()
    except ServerProxyError as error:
        return _proxy_error_response(error)


@router.get("/api/server/accounts/chatgpt", response_model=list[Account])
async def list_server_chatgpt_accounts(proxy: ServerProxyDependency):
    try:
        return await proxy.list_chatgpt_accounts()
    except ServerProxyError as error:
        return _proxy_error_response(error)


@router.post("/api/server/accounts/chatgpt", response_model=ServerSignInResponse)
async def start_server_chatgpt_sign_in(
    oauth_service: ServerOAuthDependency,
    body: ServerChatGPTSignInInput | None = Body(default=None),
):
    payload = body or ServerChatGPTSignInInput()
    try:
        result = await oauth_service.start_sign_in(
            account_id=payload.account_id,
            ssh_user=payload.ssh_user,
            ssh_port=payload.ssh_port,
            ssh_password=payload.ssh_password,
        )
        return JSONResponse(
            result.model_dump(mode="json"),
            headers={"Cache-Control": "no-store"},
        )
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    except ServerOAuthBusyError as error:
        return JSONResponse(
            {"error": str(error), "code": "oauth_busy"}, status_code=409
        )
    except ServerOAuthCancelledError as error:
        return JSONResponse(
            {"error": str(error), "code": "oauth_cancelled"}, status_code=409
        )
    except HostKeyMismatchError as error:
        return JSONResponse(
            {"error": str(error), "code": "host_key_mismatch"}, status_code=409
        )
    except SshAuthError as error:
        return JSONResponse(
            {"error": str(error), "code": "ssh_auth_failed"}, status_code=401
        )
    except SshUnreachableError as error:
        return JSONResponse(
            {"error": str(error), "code": "ssh_unreachable"}, status_code=502
        )
    except ServerProxyError as error:
        return _proxy_error_response(error)


@router.get(
    "/api/server/accounts/chatgpt/sign-in/{sign_in_id}",
    response_model=SignInStatus,
)
async def get_server_chatgpt_sign_in_status(
    sign_in_id: str,
    oauth_service: ServerOAuthDependency,
):
    try:
        return await oauth_service.poll_status(sign_in_id)
    except ServerProxyError as error:
        return _proxy_error_response(error)


@router.delete("/api/server/accounts/chatgpt/{account_id}", status_code=204)
async def remove_server_chatgpt_account(
    account_id: str,
    proxy: ServerProxyDependency,
    oauth_service: ServerOAuthDependency,
):
    try:
        await proxy.remove_chatgpt_account(account_id)
    except ServerProxyError as error:
        return _proxy_error_response(error)
    await oauth_service.cancel_for_account(account_id)
    return Response(status_code=204)


@router.get("/api/server/devices", response_model=DeviceList)
async def list_server_devices(proxy: ServerProxyDependency):
    try:
        return DeviceList(devices=await proxy.list_devices())
    except ServerProxyError as error:
        return _proxy_error_response(error)


@router.post("/api/server/pairing-code", response_model=PairingCodeResponse)
async def create_server_pairing_code(proxy: ServerProxyDependency):
    try:
        return PairingCodeResponse.model_validate(await proxy.create_pairing_code())
    except ServerProxyError as error:
        return _proxy_error_response(error)


@router.delete("/api/server/devices/{id}", response_model=Ok)
async def revoke_server_device(id: str, proxy: ServerProxyDependency):
    try:
        await proxy.revoke_device(id)
        return Ok()
    except ServerProxyError as error:
        return _proxy_error_response(error)
