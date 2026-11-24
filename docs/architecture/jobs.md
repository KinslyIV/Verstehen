# Background jobs and workers

Owns the four background workers (`research`, `pdf`, `visual`, `demo`), the job lifecycle from
dispatch to delivery, and how a finished result reaches the teacher: injected into a running
turn, carried by the answer turn, or by a wake turn of an idle session.

LearnHarness spec: [subagents and background work](../learnharness/subagents-and-background-work.md).

## Code map

Backend, `backend/src/verstehen/`:

| File | What it holds |
|---|---|
| `teaching/job_tools.py` | `JobDispatcher` and the four tools: save the job, call `start_job`, acknowledge at once. Each tool exists only while its Settings → Tools switch is on; the prober gets `research` and `pdf` only |
| `jobs/runner.py` | `JobRunner`: resolve the role model fresh, ask background consent, run the worker, record usage, then save result, status, and pending delivery in one update and call `wake_session` |
| `jobs/contracts.py`, `jobs/markers.py` | inputs and results per kind, LH's delivery texts, and the job markers (`steer_<job id>`) |
| `jobs/workers/admission.py` | `WorkerAdmission`: the app-wide FIFO gate on worker model requests (default 8), also used by graph extraction |
| `jobs/workers/research.py`, `search.py`, `web.py` | the researcher; native search, Tavily, or Brave; bounded public-only fetches |
| `jobs/workers/pdf.py`, `pdf_ops.py` | the PDF reader on pypdfium2 |
| `jobs/workers/visual.py` | SVG figures and photo annotation, rendered with resvg and looked at by the model |
| `jobs/workers/demo.py`, `headless.py`, `browser.py` | the demo builder, its mandatory headless check, and demo-browser discovery and download |
| `jobs/workers/common.py` | `WorkerModel`, typed `worker_tool` schema wrapper, CPU work in threads, usage |
| `session/delivery.py`, `session/context_updates.py` | `DeliveryService` (wakes) and the context-update step ([session](session.md)) |
| `session/jobs.py` | `JobService`: `GET /api/jobs` with the recovery sweep, and abort |

Frontend, `app/src/lib/jobs/`: `feed.svelte.ts` (the session's job feed), `jobs-panel.svelte` (the
right panel's Jobs tab with End), and the cards (`dispatch-card`, `marker-card`, `brief-card`,
`visual-card`, `demo-card` in a sandboxed iframe, `invert-switch`).

## How it works

- **Dispatch is fire-and-forget.** A tool call saves a `jobs` row once per tool call id and returns
  LH's acknowledgement; the turn goes on.
- **Workers are background requests.** Each run asks `ProviderPolicy.admit("background")`; a refusal
  ends the job with the kind's failure text. Every worker model request waits in `WorkerAdmission`.
- **Three delivery paths**, all with the deterministic marker id, so delivery happens once:
  1. a running turn takes the marker in its next context update (never while a question is
     pending);
  2. behind a question, it becomes eligible again once the answer starts a turn (still subject to
     background consent);
  3. an idle session gets a `steers` wake turn from `DeliveryService.pump`.
- **When a wake may start:** no turn or compaction runs, no question or dismissal pause or
  recovery is pending, and no probe handoff is owed. Wakes are triggered by events, not polling:
  a settled turn, a finished job, `chats-changed`, `compaction-changed` (finished), a settings
  save, and `GET /api/jobs`.
- **Composer steers** (`POST /api/sessions/{id}/steer`) queue in memory and land in the running
  turn's next context update, as in LH. A restart drops them.
- **Once means once saved.** The deterministic id deduplicates saved markers; a request that fails
  at dispatch still leaves its marker saved, and a Retry delivers it once.
- **Recovery.** `GET /api/jobs` runs the sweep at most once every 30 seconds: interrupted jobs re-run
  (except in a session with an active turn) and saved deliveries are restored. A shutdown leaves running jobs `running` so the next sweep picks them up.
- **Demo security.** Demo HTML runs in `<iframe sandbox="allow-scripts" srcdoc>` without
  `allow-same-origin`. The app CSP is relaxed (`'unsafe-inline'` and `https:`) so demos can load
  their CDN scripts; the sandbox and the API token still protect the app. A `srcdoc` frame inherits
  the app's CSP, and Tauri would add script hashes that void `'unsafe-inline'`, blocking every inline
  script in a demo (the size bridge too), so `dangerousDisableAssetCspModification` covers
  `script-src`. Demos are never delivered untested.
- **Wheel.** WebKitGTK does not chain the wheel out of the sandboxed frame, so scrolling stalls
  over a demo. The shell script cancels a wheel turn nothing inside the demo can scroll and posts
  `{type: 'demo-wheel', x, y}` (`demoWheel`); the card scrolls its dialog when zoomed, else the
  nearest scrolling ancestor (the transcript).
- **Zoom.** `demo-card.svelte` zooms in place: its own `<dialog>` is opened with `showModal()` and
  a spacer (`demo-spacer`) holds the card's height in the transcript, so the iframe is never
  remounted and its live state survives. The sandboxed demo cannot hand Escape to the page, so the
  demo shell script posts `{type: 'demo-escape'}` (`isDemoEscape` in `jobs.ts`) and the card closes.
  `visual-card.svelte` (figures) and `teaching/image-card.svelte` open their picture in the shared
  `components/zoom-dialog.svelte`, which renders its content only while open.
- **Artifact views.** The invert switch of figures and demos is saved in `artifact_views`, never
  sent to the model.

## Data and events

- Tables: `jobs`, `artifact_views`, `usage` ([store](store.md)).
- Markers: job results, aborts, and failures as `marker` entries.
- Notifications: `jobs-changed`; turn events `context_update` and `message_end.results`
  (dispatch acknowledgements).
- Settings: `tools` (the four switches), `worker_request_concurrency`, `search_engine`,
  `demo_browser`; Tavily
  and Brave keys in `credentials.json` (`TAVILY_API_KEY` / `BRAVE_API_KEY` win).

## Traps found in M1–M9

- **`jobs/` may not import Pydantic AI outside `jobs/workers/`**, which is why the job tools live
  in `teaching/job_tools.py` and take an injected `start_job`.
- **Account sign-in does not wake a session by itself**; the next trigger event does.
- **A failed photo annotation can leave its image file behind.** Open; see the
  [roadmap](../roadmap.md).
- **Reload aborts the `/api/jobs` poll.** Verify fixtures must ignore that aborted request, or
  `job-recovery-reload` fails intermittently.
