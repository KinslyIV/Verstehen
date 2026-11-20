import importlib
import importlib.metadata
import io
import json
import shutil
import subprocess
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
    return "one-page PDF created and opened"


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


def check_claude() -> str:
    """Prove the SDK is included and report the installed `claude`, which is optional."""
    importlib.import_module("claude_agent_sdk")
    sdk = f"SDK {importlib.metadata.version('claude-agent-sdk')}"
    cli = shutil.which("claude")
    if cli is None:
        return f"{sdk}; claude not installed"
    return f"{sdk}; claude {command_version([cli, '--version'])}"


def run_self_check() -> bool:
    checks: list[tuple[str, Callable[[], str]]] = [
        ("resvg", check_resvg),
        ("pypdfium2", check_pdfium),
        ("pillow", check_pillow),
        ("regex", check_regex),
        ("playwright", check_playwright),
        ("claude-agent-sdk", check_claude),
    ]
    results = []
    for name, check in checks:
        try:
            results.append({"name": name, "ok": True, "detail": check()})
        except Exception as error:
            results.append({"name": name, "ok": False, "detail": str(error)})
    print(json.dumps(results), flush=True)
    return all(result["ok"] for result in results)
