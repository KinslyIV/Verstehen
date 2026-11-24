import hmac
import ipaddress
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse

from verstehen.config import Settings
from verstehen.store.devices import DevicesStore

SERVER_EXEMPT_PATHS = {"/api/health", "/api/auth/pair"}


def extract_bearer_token(request: Request) -> str | None:
    """Extract a bearer token from Authorization or x-verstehen-token."""
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
        return None
    token = request.headers.get("x-verstehen-token", "").strip()
    return token or None


async def authenticate_server_request(
    request: Request, devices_store: DevicesStore
) -> JSONResponse | None:
    """Verify a server-mode bearer token, recording the device on the request."""
    if request.url.path in SERVER_EXEMPT_PATHS:
        return None
    token = extract_bearer_token(request)
    device = await devices_store.verify(token) if token else None
    if device is None:
        return JSONResponse(
            {"error": "Server API access requires a valid device bearer token."},
            status_code=401,
            headers={
                "WWW-Authenticate": "Bearer",
                "Cache-Control": "no-store",
            },
        )
    request.state.device_id = device.id
    await devices_store.touch_last_seen(device.id)
    return None


def addressed_origin(request: Request) -> tuple[str, str] | None:
    """Return the normalized Host hostname and origin, or None for an invalid Host."""
    host = request.headers.get("host")
    if not host:
        return None
    try:
        url = urlsplit(f"{request.url.scheme}://{host}")
        hostname = url.hostname
        port = url.port
        if (
            not hostname
            or url.username is not None
            or url.password is not None
            or url.path not in ("", "/")
            or url.query
            or url.fragment
        ):
            return None
        hostname = hostname.lower()
        authority = f"[{hostname}]" if ":" in hostname else hostname
        if port is not None and port != (443 if url.scheme == "https" else 80):
            authority += f":{port}"
        return hostname, f"{url.scheme}://{authority}"
    except ValueError:
        return None


def host_allowed(hostname: str, settings: Settings) -> bool:
    """Allow localhost names, any IP address, and explicitly configured hostnames."""
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return hostname in settings.allowed_hosts


def request_refusal(request: Request, settings: Settings) -> str | None:
    """Return an access-denial reason, or None when the launch mode permits the request."""
    if settings.desktop:
        supplied = request.headers.get("x-verstehen-token", "")
        if not settings.token or not hmac.compare_digest(
            supplied.encode(), settings.token.encode()
        ):
            return "Desktop API access requires the trusted Verstehen window."
        return None
    addressed = addressed_origin(request)
    if addressed is None or not host_allowed(addressed[0], settings):
        return (
            "This host name is not allowed. Use localhost or an IP address, "
            "or add the name to VERSTEHEN_ALLOWED_HOSTS."
        )
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return None
    site = request.headers.get("sec-fetch-site")
    origin = request.headers.get("origin")
    if (site is not None and site != "same-origin") or (
        origin is not None and origin != addressed[1]
    ):
        return "Cross-site requests to the Verstehen API are not allowed."
    return None
