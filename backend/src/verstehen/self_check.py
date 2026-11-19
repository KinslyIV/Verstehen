import io
import json
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
    import claude_agent_sdk

    cli = Path(claude_agent_sdk.__file__).parent / "_bundled/claude"
    return command_version([str(cli), "--version"])


def run_self_check() -> bool:
    checks: list[tuple[str, Callable[[], str]]] = [
        ("resvg", check_resvg),
        ("pypdfium2", check_pdfium),
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
