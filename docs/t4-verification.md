# T4 verification

T4 replaces the M1 static lesson with the session controller and API-backed UI. It removes the
`composer_accepts_text_but_send_is_disabled` and `enter_does_not_send_without_backend` tests.
The backend is unchanged. All browser work uses isolated temporary data and scripted fake models.

## Checks and behaviors

`make check` passed: 158 backend and 62 frontend tests. It covers backend tests, generated API freshness, lint, format, types, and browser tests.
New browser cases cover Enter/Shift+Enter, Stop, saved thread rendering, collapsed thinking,
provider failure after reload, draft restoration, Retry preserving today's draft, append-only
adoption, replacement of live slots, bounded 409 retry, and one recovery without resending input.
API cases cover split UTF-8/CRLF SSE and early EOF. The block regression checks both parse calls
and DOM mutations: finished blocks do neither while the tail changes. Existing T3 tests remain.

`make verify` passed all 17 cases. It runs the seven requested T4 flows, with dark/light variants for the main thread
and markdown, two performance flows, and the six M1 flows. Screenshots and traces use the
repository verify skill. The screenshots inspected are listed below; each directory also has
`trace.zip`. All paths below are relative to `app/verify-output/`.

- `app-reaches-sidecar.flow.ts-app-reaches-sidecar/screenshot.png`
- `layout-lesson-dark.flow.ts-layout-lesson-dark/screenshot.png`
- `layout-sidebar-collapsed.flow.ts-layout-sidebar-collapsed/screenshot.png`
- `layout-right-panel-open.flow.ts-layout-right-panel-open/screenshot.png`
- `settings-appearance-light.flow.ts-settings-appearance-light/screenshot.png`
- `settings-models-light.flow.ts-settings-models-light/screenshot.png`
- `session-new-and-stream.flow.ts-session-new-and-stream-dark/screenshot.png`
- `session-new-and-stream.flow.ts-session-new-and-stream-light/screenshot.png`
- `session-reload-mid-turn.flow.ts-session-reload-mid-turn/screenshot.png`
- `session-stop.flow.ts-session-stop/screenshot.png`
- `session-error-retry.flow.ts-session-error-retry/screenshot.png`
- `session-rename-delete.flow.ts-session-rename-delete/screenshot.png`
- `session-no-model.flow.ts-session-no-model/screenshot.png`
- `markdown-rendering.flow.ts-markdown-rendering-dark/screenshot.png`
- `markdown-rendering.flow.ts-markdown-rendering-light/screenshot.png`
- `session-performance.flow.ts-session-performance/screenshot.png`
- `session-performance-realis-1d389-ssion-performance-realistic/screenshot.png`

## Performance

Isolated runs used one worker with no checks or other flows running, the same machine and Chromium,
100 ms fake-provider chunk delay, and the backend's ~100 ms coalescing. Timing starts after the
session route loads. Input time is Playwright's composer fill action after the first prose appears;
long tasks come from PerformanceObserver. The realistic case also waits for Mermaid. These are
single samples, not statistical benchmarks; the fake provider emits three or four large text chunks.

| Fixture | Whole-reply input | Block input | Whole-reply longest task | Block longest task |
|---|---:|---:|---:|---:|
| One roughly 4,750-word paragraph plus T3 fixtures | 41 ms | 41 ms | 289 ms | 337 ms |
| Realistic 4,536 words, short paragraphs, headings, lists, four code blocks, math, Mermaid | 575 ms | 412 ms | 152 ms | 282 ms |

The realistic input action improves with blocks, while peak tasks worsen. Keep the LH block
approach as authorized, without claiming uniformly smooth streaming. One huge paragraph remains
one changing block in LH too. Full-suite performance attachments run under contention and are
not the isolated comparison above. No further profiling or renderer redesign was authorized.

## Decisions and remaining scope

The two recorded orchestrator decisions map the current official AI Elements registry names to
M2's intended pieces, and apply streamdown's top-level block approach after the isolated stall.
No LearnHarness/doc behavior mismatch was found. Model setup stays in M3, questions in M4,
and plan content in M5. Orchestrator review and eventual desktop packaging remain.
