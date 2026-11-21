import asyncio
import ipaddress
import re
import socket
import uuid
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx2 as httpx

from verstehen.jobs.contracts import is_web_source_url
from verstehen.jobs.workers.common import run_cpu
from verstehen.jobs.workers.pdf_ops import pdf_extract, pdf_info, pdf_search
from verstehen.jobs.workers.search import SearchChoice, brave_search, tavily_search

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
NO_SEARCH = "web_search is not available: no search engine is configured. Set a Tavily, Brave, Exa, Firecrawl, or Ollama search API key in settings. Report in your brief that web search is unavailable."


async def resolve_addresses(host: str, port: int) -> list[str]:
    addresses = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    )
    return list(dict.fromkeys(str(address[4][0]) for address in addresses))


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.strip("[]"))
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        blocked = [
            "0.0.0.0/8",
            "10.0.0.0/8",
            "100.64.0.0/10",
            "127.0.0.0/8",
            "169.254.0.0/16",
            "172.16.0.0/12",
            "192.0.0.0/24",
            "192.0.2.0/24",
            "192.88.99.0/24",
            "192.168.0.0/16",
            "198.18.0.0/15",
            "198.51.100.0/24",
            "203.0.113.0/24",
            "224.0.0.0/4",
            "240.0.0.0/4",
            "::/128",
            "::1/128",
            "64:ff9b::/96",
            "64:ff9b:1::/48",
            "100::/64",
            "2001:db8::/32",
            "2002::/16",
            "fc00::/7",
            "fe80::/10",
            "ff00::/8",
        ]
        return not any(ip in ipaddress.ip_network(network) for network in blocked)
    except ValueError:
        return False


async def safe_fetch(
    url: str,
    client: httpx.AsyncClient,
    *,
    cap: int = 5 * 1024 * 1024,
    timeout: int = 30,
    resolve: Callable[[str, int], Awaitable[list[str]]] = resolve_addresses,
) -> tuple[httpx.Response, str]:
    for _ in range(21):
        parsed = httpx.URL(url)
        if parsed.scheme not in ("http", "https") or not parsed.host:
            raise ValueError("Only http(s) URLs are supported")
        host = parsed.host
        try:
            ipaddress.ip_address(host)
            addresses = [host]
        except ValueError:
            addresses = await resolve(
                host, parsed.port or (443 if parsed.scheme == "https" else 80)
            )
        if not addresses or any(
            not is_public_address(address) for address in addresses
        ):
            raise ValueError(
                f"refusing to connect to a private or local address ({host})"
            )
        target = parsed.copy_with(host=addresses[0])
        headers = {
            "User-Agent": USER_AGENT,
            "Host": parsed.netloc.decode(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with client.stream(
            "GET",
            target,
            headers=headers,
            extensions={"sni_hostname": host},
            timeout=timeout,
            follow_redirects=False,
        ) as response:
            if response.is_redirect:
                url = str(parsed.join(response.headers["location"]))
                continue
            if not response.is_success:
                raise ValueError(
                    f"HTTP {response.status_code} {response.reason_phrase}"
                )
            if int(response.headers.get("content-length", 0)) > cap:
                raise ValueError(
                    "PDF too large (over 25 MB)"
                    if cap > 5 * 1024 * 1024
                    else "Response too large"
                )
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > cap:
                    raise ValueError(
                        "PDF too large (over 25 MB)"
                        if cap > 5 * 1024 * 1024
                        else "Response too large"
                    )
            return httpx.Response(
                response.status_code, headers=response.headers, content=bytes(data)
            ), url
    raise ValueError("Too many redirects")


class ReadableHTML(HTMLParser):
    """Extract visible article text, headings, and links for the researcher's web context."""

    def __init__(self):
        super().__init__()
        self.body: list[str] = []
        self.title: list[str] = []
        self.hidden = 0
        self.in_title = False
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav", "footer"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True
        if self.hidden:
            return
        if tag in {"p", "div", "article", "main", "br", "li", "pre"}:
            self.body.append("\n")
        if re.fullmatch("h[1-6]", tag):
            self.body.append("\n" + "#" * int(tag[1]) + " ")
        if tag == "a":
            self.links.append(dict(attrs).get("href") or "")
            self.body.append("[")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False
        if not self.hidden and tag == "a" and self.links:
            self.body.append(f"]({self.links.pop()})")
        if not self.hidden and tag in {"p", "div", "article", "main", "li", "pre"}:
            self.body.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title.append(data)
        elif not self.hidden:
            self.body.append(data)


def truncate(content: str) -> str:
    return (
        content
        if len(content) <= 40000
        else content[:40000] + "\n\n[Truncated at 40000 characters]"
    )


async def web_fetch(
    url: str,
    client: httpx.AsyncClient,
    *,
    resolve: Callable[[str, int], Awaitable[list[str]]] = resolve_addresses,
) -> str:
    if not is_web_source_url(url):
        return f'web_fetch failed: invalid URL "{url}"'
    try:
        response, final_url = await safe_fetch(url, client, resolve=resolve)
        content_type = response.headers.get("content-type", "")
        if "application/pdf" in content_type:
            return "web_fetch: this URL is a PDF document — call web_fetch_pdf on it to download and read it."
        if re.search(r"image/|audio/|video/|zip|octet-stream", content_type):
            raise ValueError(f"Unsupported content type: {content_type.split(';')[0]}")
        source = f"Source: {final_url} (HTTP {response.status_code})"
        if "html" not in content_type:
            return source + "\n\n" + truncate(response.text)
        parser = ReadableHTML()
        parser.feed(response.text)
        content = "".join(parser.body).strip()
        if len(content) >= 200:
            title = "".join(parser.title).strip()
            return (
                (f"# {title}\n\n" if title else "")
                + source
                + "\n\n---\n\n"
                + truncate(content)
            )
        try:
            fallback, _ = await safe_fetch(
                "https://r.jina.ai/" + url, client, resolve=resolve
            )
            marker = "Markdown Content:"
            markdown = (
                fallback.text.split(marker, 1)[1].strip()
                if marker in fallback.text
                else ""
            )
            if len(markdown) >= 200 and not markdown.startswith("Loading..."):
                return truncate(markdown)
        except Exception:
            pass
        raise ValueError(
            "Could not extract readable content (the page may be JavaScript-rendered)"
        )
    except Exception as error:
        return f"web_fetch failed for {url}: {error}"


async def web_search(
    query: str,
    count: int,
    choice: SearchChoice,
    keys: dict[str, str],
    client: httpx.AsyncClient,
) -> list[dict[str, str]] | str:
    if choice not in ("tavily", "brave"):
        return NO_SEARCH
    try:
        search = tavily_search if choice == "tavily" else brave_search
        return [
            hit.model_dump() for hit in await search(query, count, keys[choice], client)
        ]
    except Exception as error:
        return f"web_search failed: {error}"


async def web_fetch_pdf(
    url: str,
    directory: Path,
    client: httpx.AsyncClient,
    *,
    resolve: Callable[[str, int], Awaitable[list[str]]] = resolve_addresses,
) -> dict[str, Any] | str:
    if not is_web_source_url(url):
        return f'web_fetch_pdf failed: invalid URL "{url}"'
    try:
        response, _ = await safe_fetch(
            url, client, cap=25 * 1024 * 1024, timeout=60, resolve=resolve
        )
        content_type = response.headers.get("content-type", "")
        if "application/pdf" not in content_type.lower() and not urlparse(
            url
        ).path.lower().endswith(".pdf"):
            raise ValueError(
                f"Not a PDF (content-type {content_type.split(';')[0] or 'unknown'})"
            )
        if not response.content:
            raise ValueError("Empty response")
        slug = (
            re.sub(
                r"[^A-Za-z0-9._-]+",
                "-",
                urlparse(url).path.split("/")[-1] or "document",
            ).strip("-")[-80:]
            or "document"
        )
        path = (
            directory
            / f"{re.sub(r'\.pdf$', '', slug, flags=re.I)}-{uuid.uuid4().hex[:6]}.pdf"
        )
        await run_cpu(path.write_bytes, response.content)
        try:
            info = await run_cpu(pdf_info, path)
        except Exception:
            path.unlink(missing_ok=True)
            raise ValueError("The download is not a readable PDF") from None
        return {
            "path": str(path),
            "url": url,
            "page_count": info["page_count"],
            "size_class": size_class(info["page_count"]),
            "mean_text_length": info["mean_text_length"],
            "flagged_pages": [
                p["page"]
                for p in info["pages"]
                if p["math_density"] >= 0.03 or p["image_count"] > 0
            ][:30],
        }
    except Exception as error:
        return f"web_fetch_pdf failed for {url}: {error}"


def size_class(count: int) -> str:
    return "short" if count <= 10 else "medium" if count <= 40 else "long"


async def downloaded_pdf_tool(name: str, args: dict[str, Any], directory: Path) -> Any:
    path = (directory / str(args.get("path", ""))).resolve()
    if path == directory.resolve() or not path.is_relative_to(directory.resolve()):
        return f"{name} failed: path must stay inside this job's download dir"
    try:
        if name == "pdf_info":
            info = await run_cpu(pdf_info, path)
            return {key: value for key, value in info.items() if key != "path"} | {
                "size_class": size_class(info["page_count"])
            }
        if name == "pdf_extract":
            return (await run_cpu(pdf_extract, path, str(args.get("pages", "all"))))[0]
        return {
            "hits": await run_cpu(pdf_search, path, str(args.get("query", "")), 3, True)
        }
    except Exception as error:
        return f"{name} failed: {error}"
