from typing import Annotated

from pydantic import Field
from pydantic_ai import Agent
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from verstehen.jobs.contracts import DemoInput, DemoResult
from verstehen.jobs.workers.common import (
    ActivityCallback,
    UsageCallback,
    WorkerModel,
    ignore_activity,
    worker_tool,
)
from verstehen.jobs.workers.headless import (
    NO_BROWSER,
    DemoRunner,
    DemoRunResult,
    failure_summary,
    format_run_result,
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

WRITE_DESCRIPTION = "Write the complete self-contained HTML document for the demo (overwrites any previous version). Always follow with run_demo to test it headlessly."
RUN_DESCRIPTION = "Headlessly execute the current demo in a browser and report console errors, uncaught errors, and failed requests. Optionally pass a probe expression to assert on page state."


async def run_demo_builder(
    input: DemoInput,
    model: Model,
    *,
    runner: DemoRunner | None,
    on_activity: ActivityCallback | None = None,
    on_usage: UsageCallback | None = None,
    max_steps: int = 24,
) -> DemoResult:
    title = input.title.strip() or "Interactive demo"

    def failed(reason: str) -> DemoResult:
        return DemoResult(title=title, html="", notes=f"FAILED: {reason}")

    if not runner:
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
    note = on_activity or ignore_activity
    current = tested = ""
    last_result: DemoRunResult | None = None

    async def write(
        html: Annotated[
            str,
            Field(
                description="The complete HTML document: <!doctype html>…</html>, all JS inline."
            ),
        ],
    ) -> str:
        nonlocal current
        await note("write_demo")
        if not html.strip():
            return "ERROR: empty document — write the full HTML."
        current = html
        await note(f"write_demo: {len(html) / 1024:.1f} KB")
        return f"Saved ({len(html)} bytes). Now call run_demo to test it — never deliver untested."

    async def run(
        probe: Annotated[
            str,
            Field(
                description="Optional JS expression evaluated in the page after settling, e.g. \"document.querySelectorAll('input').length\"."
            ),
        ] = "",
    ) -> str:
        nonlocal tested, last_result
        await note("run_demo")
        if not current:
            return "ERROR: nothing to run — call write_demo first."
        try:
            last_result = await runner(current, probe)
            tested = current
            await note(
                "run_demo: clean"
                if last_result.ok
                else f"run_demo: {summarize_counts(last_result)}"
            )
            return format_run_result(last_result)
        except Exception as error:
            await note("run_demo: browser error")
            return f"HEADLESS ERROR (retrying may help): {error}"

    agent = Agent(
        WorkerModel(model, "demoBuilder", on_usage),
        system_prompt=INSTRUCTIONS,
        deps_type=type(None),
        output_type=str | None,
        tools=[
            worker_tool(write, "write_demo", WRITE_DESCRIPTION),
            worker_tool(run, "run_demo", RUN_DESCRIPTION),
        ],
        retries=max_steps,
    )
    final_text = ""
    try:
        final_text = (
            (
                await agent.run(
                    prompt, usage_limits=UsageLimits(request_limit=max_steps)
                )
            ).output
            or ""
        ).strip()
    except UsageLimitExceeded:
        pass
    except Exception as error:
        return failed(f"the builder crashed — {error}")
    if not current:
        return failed(
            "the builder never wrote a demo."
            + (f" ({final_text[:300]})" if final_text else "")
        )
    if tested != current or last_result is None or not last_result.ok:
        await note("final verification")
        try:
            last_result = await runner(current)
        except Exception as error:
            return failed(f"final verification crashed — {error}")
        if not last_result.ok:
            return failed(
                f"the demo never passed headless verification ({failure_summary(last_result)})."
            )
    return DemoResult(title=title, html=current, notes=final_text or None)
