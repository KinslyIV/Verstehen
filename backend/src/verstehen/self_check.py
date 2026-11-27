import asyncio
import importlib
import importlib.metadata
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path


def check_resvg() -> str:
    import resvg_py

    png = resvg_py.svg_to_bytes(
        svg_string='<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
    )
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("SVG renderer did not return PNG bytes")
    return f"PNG rendered ({len(png)} bytes)"


def check_pdfium() -> str:
    import pypdfium2 as pdfium

    buffer = io.BytesIO()
    with pdfium.PdfDocument.new() as document:
        document.new_page(72, 72).close()
        document.save(buffer)
    with pdfium.PdfDocument(buffer.getvalue()) as document:
        if len(document) != 1:
            raise RuntimeError("PDF page count is not 1")
        page = document[0]
        try:
            bitmap = page.render(scale=1)
            bitmap.close()
        finally:
            page.close()
    return "one-page PDF created, opened, and rendered"


def check_pillow() -> str:
    from PIL import Image

    pixel = (35, 70, 105)
    buffer = io.BytesIO()
    with Image.new("RGB", (1, 1), pixel) as image:
        image.save(buffer, format="PNG")
    buffer.seek(0)
    with Image.open(buffer, formats=["PNG"]) as decoded:
        if decoded.size != (1, 1) or decoded.getpixel((0, 0)) != pixel:
            raise RuntimeError("PNG did not preserve the original pixel")
    return "one-pixel PNG encoded and decoded"


def check_regex() -> str:
    import regex

    expression = regex.compile(r"\p{Letter}+")
    if expression.fullmatch("Verstehen", timeout=1.0) is None:
        raise RuntimeError("Regex did not match the expected text")
    return "pattern compiled and matched with a timeout"


def check_prompts() -> str:
    from verstehen.teaching.prompts import FRAGMENT_RE, PROMPTS_DIR

    if not (PROMPTS_DIR / "system-prompt.md").is_file():
        raise RuntimeError("system-prompt.md is missing")
    if not (PROMPTS_DIR / "chat" / "guide.md").is_file():
        raise RuntimeError("chat/guide.md is missing")
    counts = {}
    for directory in ("prober", "teacher", "shared", "practice", "chat", "side-chat"):
        folder = PROMPTS_DIR / directory
        counts[directory] = (
            sum(
                1
                for path in folder.iterdir()
                if path.is_file() and FRAGMENT_RE.fullmatch(path.name)
            )
            if folder.is_dir()
            else 0
        )
        if not counts[directory]:
            raise RuntimeError(f"No {directory} prompt fragments are bundled")
    return ", ".join(f"{name} {count}" for name, count in counts.items())


def command_version(command: list[str]) -> str:
    return subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=20
    ).stdout.strip()


def check_playwright() -> str:
    import playwright

    driver = Path(playwright.__file__).parent / "driver"
    return command_version(
        [str(driver / "node"), str(driver / "package/cli.js"), "--version"]
    )


SELF_CHECK_PAGE = "<!doctype html><title>Self-check</title><p>offline</p>"
SELF_CHECK_PROBE = "document.querySelector('p').textContent"


def is_desktop_bundle() -> bool:
    return importlib.util.find_spec("PySide6") is not None


def check_qt_demo() -> str:
    """Run an offline demo page through the desktop's QtWebEngine runner."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from verstehen.desktop.demo_runner import run_with_demo_runner

    result = run_with_demo_runner(
        lambda runner: runner(SELF_CHECK_PAGE, SELF_CHECK_PROBE)
    )
    if not result.ok or result.probe_result != "offline":
        raise RuntimeError(f"Offline Qt demo page failed: {result.model_dump_json()}")
    return "offline Qt demo page loaded and probed"


def check_headless() -> str:
    from playwright.sync_api import sync_playwright

    from verstehen.jobs.workers.headless import run_demo

    executable = next(
        (
            found
            for name in (
                "chromium",
                "chromium-browser",
                "google-chrome-stable",
                "google-chrome",
            )
            if (found := shutil.which(name))
        ),
        None,
    )
    if executable is None:
        with sync_playwright() as playwright:
            installed = Path(playwright.chromium.executable_path)
        executable = str(installed) if installed.is_file() else None
    if executable is None:
        return "no browser found; optional headless check skipped"
    result = asyncio.run(
        run_demo(
            SELF_CHECK_PAGE,
            executable,
            SELF_CHECK_PROBE,
        )
    )
    if not result.ok or result.probe_result != "offline":
        raise RuntimeError(f"Offline headless page failed: {result.model_dump_json()}")
    return "offline headless page loaded and probed"


def check_claude() -> str:
    """Prove the SDK is included and report the installed `claude`, which is optional."""
    importlib.import_module("claude_agent_sdk")
    sdk = f"SDK {importlib.metadata.version('claude-agent-sdk')}"
    cli = shutil.which("claude")
    if cli is None:
        return f"{sdk}; claude not installed"
    return f"{sdk}; claude {command_version([cli, '--version'])}"


async def check_core_mcp_plugin(data_dir: Path) -> None:
    from verstehen.plugins.core import CORE_PLUGINS
    from verstehen.plugins.service import PluginService
    from verstehen.store.plugins import PluginsStore

    service = PluginService(
        PluginsStore(data_dir),
        data_dir / "plugins",
        importlib.metadata.version("verstehen"),
        True,
        lambda: None,
        lambda *_: None,
        core_plugins=CORE_PLUGINS,
    )
    try:
        await service.discover()
        plugin_id = "mcp-servers"
        plugin = service.plugins[plugin_id]
        if not plugin.info.core or plugin.info.status != "disabled":
            raise RuntimeError(
                plugin.info.error or "Core MCP Servers plugin was not discovered"
            )
        await service.set_enabled(plugin_id, True)
        await service.settled()
        if plugin.info.status != "active":
            raise RuntimeError(
                plugin.info.error or "Core MCP Servers plugin did not start"
            )
        if await service.call(plugin_id, "get_servers", None) != {} or not isinstance(
            service.file(plugin_id, "main.js"), tuple
        ):
            raise RuntimeError(
                "Core MCP Servers plugin backend or frontend did not load"
            )
    finally:
        await service.close()


def check_mcp() -> str:
    """Prove the MCP client stack used by plugin toolsets is bundled and importable."""
    from pydantic_ai.mcp import MCPToolset

    fastmcp = importlib.metadata.version("fastmcp-slim")
    mcp = importlib.metadata.version("mcp")
    summary = f"{MCPToolset.__name__}; fastmcp-slim {fastmcp}, mcp {mcp}"
    if is_desktop_bundle():
        with tempfile.TemporaryDirectory(prefix="verstehen-core-plugins-") as directory:
            asyncio.run(check_core_mcp_plugin(Path(directory)))
        summary += "; core MCP Servers plugin loaded"
    return summary


def run_self_check() -> bool:
    demo_checks = (
        [("qt-demo", check_qt_demo)]
        if is_desktop_bundle()
        else [("playwright", check_playwright), ("headless", check_headless)]
    )
    checks: list[tuple[str, Callable[[], str]]] = [
        ("resvg", check_resvg),
        ("pypdfium2", check_pdfium),
        ("pillow", check_pillow),
        ("regex", check_regex),
        ("prompts", check_prompts),
        *demo_checks,
        ("claude-agent-sdk", check_claude),
        ("mcp", check_mcp),
    ]
    results = []
    for name, check in checks:
        try:
            results.append({"name": name, "ok": True, "detail": check()})
        except Exception as error:
            results.append({"name": name, "ok": False, "detail": str(error)})
    print(json.dumps(results), flush=True)
    return all(result["ok"] for result in results)
