import asyncio

from pydantic_ai.models import Model

from verstehen.jobs.contracts import DemoInput, DemoResult
from verstehen.jobs.workers.common import (
    ActivityCallback,
    UsageCallback,
    WorkerLoop,
    calls,
    text,
    tool_result,
)
from verstehen.jobs.workers.headless import (
    NO_BROWSER,
    DemoRunResult,
    failure_summary,
    format_run_result,
    run_demo,
    summarize_counts,
)

INSTRUCTIONS = """You are a demo builder — a specialist sub-agent inside a learning application. You
receive a brief for ONE interactive teaching instrument and deliver a single self-contained HTML document
that runs it. You never see the lesson; the brief is everything you know.

Runtime contract (the document runs in a sandboxed iframe, sandbox="allow-scripts", opaque origin):
- Single file. Vanilla JS + Canvas 2D or SVG. CDN imports (e.g. a plotting or math library) are allowed
  when they genuinely help — but prefer dependency-free; you own the failure if a CDN import fails.
- NO localStorage, sessionStorage, or document.cookie — the sandbox makes them throw.
- The parent sizes the iframe to the document height automatically; just build normal flowing layout.
  Make the demo fill the width and size its own height sensibly.

Build quality:
- The demo must directly serve the brief: every control named in the brief must exist and do the thing.
- Controls need labels; sliders/inputs need current-value readouts. A learner should operate it unguided.
- Smooth enough interaction; requestAnimationFrame for animation, not setInterval when it matters.
- Dark-mode neutral: pick a clean light background for the demo area so it reads on any card.

THE HOUSE RULE — never deliver untested:
1. Call write_demo with the complete HTML document.
2. Call run_demo. It loads the file in a headless browser, waits ~2s, and reports console errors, uncaught
   errors (window.onerror), and failed requests. Optionally pass a probe: a JS expression evaluated in
   the page (e.g. "typeof window.simulate === 'function'" or a state assertion) to check deeper.
3. If run_demo reports problems, FIX the document and call write_demo again, then run_demo again.
   Iterate until run_demo reports PASSED.
4. Only then finish. Your final message is 1-3 sentences of NOTES for the teacher (what the demo shows,
   its controls, what to try) — NEVER the HTML itself.

Never claim success you did not see: a PASSED run_demo is the only definition of done."""

SCHEMAS = [
    {
        "name": "write_demo",
        "description": "Write the complete self-contained HTML document for the demo (overwrites any previous version). Always follow with run_demo to test it headlessly.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "html": {
                    "type": "string",
                    "description": "The complete HTML document: <!doctype html>…</html>, all JS inline.",
                }
            },
            "required": ["html"],
        },
    },
    {
        "name": "run_demo",
        "description": "Headlessly execute the current demo in a browser and report console errors, uncaught errors, and failed requests. Optionally pass a probe expression to assert on page state.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "probe": {
                    "type": "string",
                    "description": "Optional JS expression evaluated in the page after settling, e.g. \"document.querySelectorAll('input').length\".",
                }
            },
            "required": [],
        },
    },
]


async def run_demo_builder(
    input: DemoInput,
    model: Model,
    *,
    executable: str | None,
    on_activity: ActivityCallback | None = None,
    on_usage: UsageCallback | None = None,
    cancellation: asyncio.Event | None = None,
    max_steps: int = 24,
) -> DemoResult:
    title = input.title.strip() or "Interactive demo"

    def failed(reason: str) -> DemoResult:
        return DemoResult(title=title, html="", notes=f"FAILED: {reason}")

    if not executable:
        return failed(NO_BROWSER)
    prompt = "\n".join(
        [
            f"Demo title: {title}",
            "Brief (all you know about the lesson — this comes from the teacher, verbatim):",
            input.brief.strip() or "(no brief)",
            "",
            "Build the demo, test it with run_demo, iterate until PASSED, then finish with your notes.",
        ]
    )
    loop = WorkerLoop(
        model,
        INSTRUCTIONS,
        prompt,
        SCHEMAS,
        role="demoBuilder",
        on_activity=on_activity,
        on_usage=on_usage,
        cancellation=cancellation,
    )
    html = tested_html = ""
    last_result: DemoRunResult | None = None
    final_text = ""
    try:
        for _ in range(max_steps):
            response = await loop.request()
            if not calls(response):
                final_text = text(response)
                break
            results = []
            for call in calls(response):
                loop.activity(call.tool_name)
                try:
                    args = loop.arguments(call)
                except ValueError as error:
                    results.append(tool_result(call, f"ERROR: {error}"))
                    continue
                if call.tool_name == "write_demo":
                    document = args.get("html")
                    if not isinstance(document, str) or not document.strip():
                        result = "ERROR: empty document — write the full HTML."
                    else:
                        html = document
                        loop.activity(f"write_demo: {len(html) / 1024:.1f} KB")
                        result = f"Saved ({len(html)} bytes). Now call run_demo to test it — never deliver untested."
                elif call.tool_name == "run_demo":
                    if not html:
                        result = "ERROR: nothing to run — call write_demo first."
                    else:
                        try:
                            last_result = await run_demo(
                                html, executable, args.get("probe")
                            )
                            tested_html = html
                            loop.activity(
                                "run_demo: clean"
                                if last_result.ok
                                else f"run_demo: {summarize_counts(last_result)}"
                            )
                            result = format_run_result(last_result)
                        except Exception as error:
                            loop.activity("run_demo: browser error")
                            result = f"HEADLESS ERROR (retrying may help): {error}"
                else:
                    result = f'ERROR: unknown tool "{call.tool_name}"'
                results.append(tool_result(call, result))
            loop.results(results)
    except Exception as error:
        return failed(f"the builder crashed — {error}")
    if not html:
        return failed(
            "the builder never wrote a demo."
            + (f" ({final_text[:300]})" if final_text else "")
        )
    if tested_html != html or last_result is None or not last_result.ok:
        loop.activity("final verification")
        try:
            last_result = await run_demo(html, executable)
        except Exception as error:
            return failed(f"final verification crashed — {error}")
        if not last_result.ok:
            return failed(
                f"the demo never passed headless verification ({failure_summary(last_result)})."
            )
    return DemoResult(title=title, html=html, notes=final_text or None)
