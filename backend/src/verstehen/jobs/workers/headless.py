import asyncio
import json
from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel, Field, JsonValue
lazy from playwright.async_api import async_playwright

ALLOWED_SCHEMES = frozenset({"http", "https", "data", "blob", "about"})
SETTLE_SECONDS = 2
LOAD_TIMEOUT_SECONDS = 30
NO_BROWSER = "No render engine available: no Chromium-family browser was found. Set one in Settings → Tools → Demo browser, install Chromium, or use “Download Chromium for demos” there. (Verification is mandatory — demos are never delivered untested.)"


class DemoRunResult(BaseModel):
    console_errors: list[str] = Field(default_factory=list)
    page_errors: list[str] = Field(default_factory=list)
    failed_requests: list[str] = Field(default_factory=list)
    probe_result: JsonValue = None
    probed: bool = False

    @property
    def ok(self) -> bool:
        return not (self.console_errors or self.page_errors or self.failed_requests)


class DemoRunner(Protocol):
    """Loads a demo document in a browser and reports what went wrong, like Playwright's `run_demo`."""

    async def __call__(self, html: str, probe: str | None = None) -> DemoRunResult: ...


# Gives the runner for the configured demo browser path, or None when no browser is available.
DemoRunnerProvider = Callable[[str | None], DemoRunner | None]


class PlaywrightDemoRunner:
    """Runs demos in the Chromium-family browser at `executable`, for server mode."""

    def __init__(self, executable: str) -> None:
        self.executable = executable

    async def __call__(self, html: str, probe: str | None = None) -> DemoRunResult:
        return await run_demo(html, self.executable, probe)


async def run_demo(
    html: str, executable: str, probe: str | None = None
) -> DemoRunResult:
    result = DemoRunResult(probed=bool(probe))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=executable, headless=True
        )
        try:
            context = await browser.new_context()
            page = await context.new_page()
            page.on(
                "console",
                lambda message: (
                    result.console_errors.append(message.text)
                    if message.type == "error"
                    else None
                ),
            )
            page.on("pageerror", lambda error: result.page_errors.append(str(error)))
            page.on(
                "requestfailed",
                lambda request: result.failed_requests.append(
                    f"{request.url} ({request.failure or 'failed'})"
                ),
            )

            async def guard(route):
                scheme = route.request.url.split(":", 1)[0]
                if scheme in ALLOWED_SCHEMES:
                    await route.continue_()
                else:
                    await route.abort("accessdenied")

            await page.route("**/*", guard)
            try:
                await page.set_content(
                    html, wait_until="load", timeout=LOAD_TIMEOUT_SECONDS * 1000
                )
                await asyncio.sleep(SETTLE_SECONDS)
                if probe:
                    try:
                        result.probe_result = await page.evaluate(probe)
                    except Exception as error:
                        result.page_errors.append(f"probe failed: {error}")
            except Exception as error:
                result.page_errors.append(str(error))
            await context.close()
        finally:
            await browser.close()
    return result


def summarize_counts(result: DemoRunResult) -> str:
    counts = []
    for values, label in [
        (result.console_errors, "console error"),
        (result.page_errors, "page error"),
        (result.failed_requests, "failed request"),
    ]:
        if values:
            counts.append(f"{len(values)} {label}{'s' if len(values) != 1 else ''}")
    return ", ".join(counts) or "ok"


def failure_summary(result: DemoRunResult | None) -> str:
    if result is None:
        return "never tested"
    details = (result.console_errors + result.page_errors + result.failed_requests)[:5]
    return summarize_counts(result) + (" — " + " | ".join(details) if details else "")


def format_run_result(result: DemoRunResult) -> str:
    if result.ok:
        probe = (
            f" Probe result: {json.dumps(result.probe_result, separators=(',', ':'))}."
            if result.probed
            else ""
        )
        return f"PASSED: no console errors, no uncaught errors, no failed requests.{probe} If you are satisfied, finish with your notes; otherwise keep improving and re-test."
    sections = [f"FAILED: {summarize_counts(result)}."]
    for label, values in [
        ("Console errors", result.console_errors),
        ("Uncaught errors", result.page_errors),
        ("Failed requests", result.failed_requests),
    ]:
        if values:
            sections.append(
                label + ":\n" + "\n".join(f"- {value}" for value in values[:10])
            )
    return "\n".join(
        [*sections, "Fix the document (write_demo) and re-test (run_demo)."]
    )
