import asyncio
import re
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse

from verstehen.api.sessions import ApiError, Ok
from verstehen.store.devices import Device, DevicesStore

PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PAIRING_CODE_LENGTH = 8
PAIRING_TTL = timedelta(minutes=5)
RATE_LIMIT_WINDOW = timedelta(minutes=5)
MAX_FAILED_ATTEMPTS = 5


class PairingCodeManager:
    """Issue short-lived single-use pairing codes and rate-limit failed redemptions."""

    def __init__(
        self,
        *,
        ttl: timedelta = PAIRING_TTL,
        window: timedelta = RATE_LIMIT_WINDOW,
        max_failures: int = MAX_FAILED_ATTEMPTS,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.ttl = ttl
        self.window = window
        self.max_failures = max_failures
        self.monotonic_clock = monotonic_clock
        self.wall_clock = wall_clock
        self.lock = asyncio.Lock()
        self.codes: dict[str, tuple[float, str]] = {}
        self.failures: dict[str, list[float]] = {}

    @staticmethod
    def normalize(code: str) -> str:
        return re.sub(r"[\s-]+", "", code).upper()

    def _prune_codes(self, now_mono: float) -> None:
        expired = [
            code
            for code, (expires_at_mono, _) in self.codes.items()
            if now_mono >= expires_at_mono
        ]
        for code in expired:
            del self.codes[code]

    def _prune_failures(self, now_mono: float) -> None:
        cutoff = now_mono - self.window.total_seconds()
        for ip, stamps in list(self.failures.items()):
            recent = [stamp for stamp in stamps if stamp > cutoff]
            if recent:
                self.failures[ip] = recent
            else:
                del self.failures[ip]

    def issue(self, issued_by: str) -> tuple[str, datetime]:
        now_mono = self.monotonic_clock()
        self._prune_codes(now_mono)
        code = "".join(
            secrets.choice(PAIRING_ALPHABET) for _ in range(PAIRING_CODE_LENGTH)
        )
        while code in self.codes:
            code = "".join(
                secrets.choice(PAIRING_ALPHABET) for _ in range(PAIRING_CODE_LENGTH)
            )
        self.codes[code] = (now_mono + self.ttl.total_seconds(), issued_by)
        return code, self.wall_clock() + self.ttl

    def revoke_issuer(self, device_id: str) -> None:
        revoked = [
            code
            for code, (_, issuer_id) in self.codes.items()
            if issuer_id == device_id
        ]
        for code in revoked:
            del self.codes[code]

    def is_rate_limited(self, client_ip: str) -> bool:
        self._prune_failures(self.monotonic_clock())
        return len(self.failures.get(client_ip, ())) >= self.max_failures

    def record_failure(self, client_ip: str) -> None:
        now_mono = self.monotonic_clock()
        self._prune_failures(now_mono)
        self.failures.setdefault(client_ip, []).append(now_mono)

    def redeem(
        self, code: str, client_ip: str
    ) -> Literal["ok", "invalid", "rate_limited"]:
        if self.is_rate_limited(client_ip):
            return "rate_limited"
        now_mono = self.monotonic_clock()
        normalized = self.normalize(code)
        entry = self.codes.get(normalized)
        if entry is None or now_mono >= entry[0]:
            self.codes.pop(normalized, None)
            self.record_failure(client_ip)
            return "invalid"
        del self.codes[normalized]
        return "ok"


def get_devices_store(request: Request) -> DevicesStore:
    return request.app.state.devices_store


def get_pairing_code_manager(request: Request) -> PairingCodeManager:
    return request.app.state.pairing_code_manager


DevicesStoreDependency = Annotated[DevicesStore, Depends(get_devices_store)]
PairingCodeManagerDependency = Annotated[
    PairingCodeManager, Depends(get_pairing_code_manager)
]

router = APIRouter(responses={404: {"model": ApiError}})


class PairingCodeResponse(BaseModel):
    code: str
    expires_at: datetime


class PairInput(BaseModel):
    code: str
    device_name: str


class PairResponse(BaseModel):
    device_id: str
    token: str


class DeviceList(BaseModel):
    devices: list[Device]


@router.post(
    "/api/auth/pairing-code",
    response_model=PairingCodeResponse,
    responses={401: {"model": ApiError}},
)
async def create_pairing_code(
    request: Request,
    devices_store: DevicesStoreDependency,
    manager: PairingCodeManagerDependency,
):
    async with manager.lock:
        if not await devices_store.is_active(request.state.device_id):
            return JSONResponse(
                {"error": "Server API access requires a valid device bearer token."},
                status_code=401,
                headers={
                    "WWW-Authenticate": "Bearer",
                    "Cache-Control": "no-store",
                },
            )
        code, expires_at = manager.issue(request.state.device_id)
    return PairingCodeResponse(code=code, expires_at=expires_at)


@router.post(
    "/api/auth/pair",
    response_model=PairResponse,
    responses={400: {"model": ApiError}, 429: {"model": ApiError}},
)
async def pair_device(
    body: PairInput,
    request: Request,
    devices_store: DevicesStoreDependency,
    manager: PairingCodeManagerDependency,
):
    client_ip = request.client.host if request.client else "unknown"
    if manager.is_rate_limited(client_ip):
        return JSONResponse(
            {"error": "Too many failed pairing attempts. Try again later."},
            status_code=429,
        )
    device_name = body.device_name.strip()
    if not device_name:
        return JSONResponse(
            {"error": "Device name must not be empty."},
            status_code=400,
        )
    outcome = manager.redeem(body.code, client_ip)
    if outcome == "rate_limited":
        return JSONResponse(
            {"error": "Too many failed pairing attempts. Try again later."},
            status_code=429,
        )
    if outcome == "invalid":
        return JSONResponse(
            {"error": "Invalid or expired pairing code."},
            status_code=400,
        )
    device, token = await devices_store.create(device_name)
    return PairResponse(device_id=device.id, token=token)


@router.get(
    "/api/auth/devices",
    response_model=DeviceList,
    responses={401: {"model": ApiError}},
)
async def list_devices(
    devices_store: DevicesStoreDependency,
):
    return DeviceList(devices=await devices_store.list())


@router.delete(
    "/api/auth/devices/{id}",
    response_model=Ok,
    responses={401: {"model": ApiError}},
)
async def revoke_device(
    id: str,
    devices_store: DevicesStoreDependency,
    manager: PairingCodeManagerDependency,
):
    async with manager.lock:
        if not await devices_store.revoke(id):
            return JSONResponse({"error": "Device not found."}, status_code=404)
        manager.revoke_issuer(id)
    return Ok()
