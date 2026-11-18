import hmac
import ipaddress
from urllib.parse import urlsplit

from starlette.requests import Request

from verstehen.config import Settings


def addressed_origin(request: Request) -> tuple[str, str] | None:
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
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return hostname in settings.allowed_hosts


def request_refusal(request: Request, settings: Settings) -> str | None:
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
