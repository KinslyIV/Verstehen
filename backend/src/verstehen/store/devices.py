import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel

from verstehen.store.database import Database

LAST_SEEN_THROTTLE_SECONDS = 60.0


class Device(BaseModel):
    id: str
    name: str
    created_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None


def hash_token(token: str) -> str:
    """Return the lowercase SHA-256 hex digest of a device bearer token."""
    return hashlib.sha256(token.encode()).hexdigest()


class DevicesStore:
    """Persist paired devices and verify SHA-256-hashed bearer tokens."""

    def __init__(
        self,
        database: Database,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.database = database
        self._clock = clock
        self._last_touched: dict[str, float] = {}

    async def create(self, name: str) -> tuple[Device, str]:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Device name must not be empty.")
        token = secrets.token_urlsafe(48)
        token_hash = hash_token(token)
        device = Device(
            id=uuid4().hex,
            name=cleaned,
            created_at=datetime.now(UTC),
        )
        async with self.database.transaction() as connection:
            await connection.execute(
                "INSERT INTO devices (id, name, token_hash, created_at, last_seen_at, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    device.id,
                    device.name,
                    token_hash,
                    device.created_at.isoformat(),
                    None,
                    None,
                ),
            )
        return device, token

    async def verify(self, token: str) -> Device | None:
        if not token:
            return None
        candidate_hash = hash_token(token)
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT id, name, created_at, last_seen_at, revoked_at, token_hash "
                "FROM devices WHERE token_hash = ? AND revoked_at IS NULL",
                (candidate_hash,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None or not hmac.compare_digest(
            row[5].encode(), candidate_hash.encode()
        ):
            return None
        return Device.model_validate(dict(zip(Device.model_fields, row[:5])))

    async def touch_last_seen(self, device_id: str) -> None:
        now = self._clock()
        last = self._last_touched.get(device_id)
        if last is not None and now - last < LAST_SEEN_THROTTLE_SECONDS:
            return
        self._last_touched[device_id] = now
        seen_at = datetime.now(UTC).isoformat()
        async with self.database.transaction() as connection:
            await connection.execute(
                "UPDATE devices SET last_seen_at = ? WHERE id = ?",
                (seen_at, device_id),
            )

    async def list(self) -> list[Device]:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT id, name, created_at, last_seen_at, revoked_at "
                "FROM devices ORDER BY created_at DESC, rowid DESC"
            ) as cursor:
                return [
                    Device.model_validate(dict(zip(Device.model_fields, row)))
                    for row in await cursor.fetchall()
                ]

    async def is_active(self, device_id: str) -> bool:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT 1 FROM devices WHERE id = ? AND revoked_at IS NULL",
                (device_id,),
            ) as cursor:
                return await cursor.fetchone() is not None

    async def revoke(self, device_id: str) -> bool:
        async with self.database.transaction() as connection:
            async with connection.execute(
                "SELECT revoked_at FROM devices WHERE id = ?", (device_id,)
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return False
            if row[0] is None:
                await connection.execute(
                    "UPDATE devices SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                    (datetime.now(UTC).isoformat(), device_id),
                )
        self._last_touched.pop(device_id, None)
        return True
