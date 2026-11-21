# M7 plan: background jobs and workers

> Status: **approved by the user, 2026-11-20.** Decisions are in
> [decisions](../decisions.md). LearnHarness references are at commit `cb25c8e` (checkout:
> `/home/immata/learnharness`). Spec: [subagents and background work](../learnharness/subagents-and-background-work.md),
> [turn lifecycle](../learnharness/turn-lifecycle.md), and the async protocol comment in
> `src/core/contracts/jobs.ts:152-198`. Where a doc and the LH code disagree, the code is right.

**Done when:** the teacher calls `research`, `pdf`, `visual`, or `demo` mid-turn, gets LH's
fire-and-forget acknowledgement, and keeps teaching. The thread shows a dispatch card with the
job's live activity, and the right panel's Jobs tab lists it with elapsed time, cost label, detail,
and End. When the worker finishes, its result reaches the teacher: injected before the next model
call if a turn is running, otherwise by an idle wake turn that starts by itself. The thread shows
the result card (brief with sources, PDF brief with pages, figure, annotated photo, or tested
demo in its sandboxed iframe). A result that finishes while a question is pending waits and
rides the answer turn. A learner message sent while a turn runs is steered into it. End aborts a
job and the teacher is told. After a restart, pending deliveries arrive and interrupted workers
re-run when the session's jobs are next fetched. `show_image` shows a learner's image file.
Settings → Tools holds the tool switches, worker concurrency, search keys, and demo browser.
`make check`, `make verify`, and `make verify-live` pass; the feature map and status are updated.

## User decisions for M7

1. **Two groups of tasks.** Group 1 (T1–T3) touches no session core and starts now, off `main`.
   Group 2 (T4–T5) starts only after M6 merges into `main`, rebased on it.
2. **Learner images in M7** are `show_image` and the annotated-photo snapshot of `visual` with
   `image`, both stored with M5's image store in `<data dir>/images/<sha256>.<ext>`. LH's composer
   paperclip and drag-and-drop path chips are not in M7.
3. **Search keys** for Tavily and Brave live in `<data dir>/credentials.json` (0600, never in
   SQLite, never returned unmasked). `TAVILY_API_KEY` / `BRAVE_API_KEY` in the environment win, as
   in LH (`src/server/keys.ts`). Settings → Tools → Research has one masked key field per engine
   (set, clear, LH's docs link).
4. **A "Search engine" setting picks the researcher's search:** Native, Tavily, or Brave, default
   Native (`search_engine`, Settings → Tools → Research). Tavily and Brave can be picked only while
   their key is set. With native search in use, the researcher gets Pydantic AI's `WebSearch` and
   no `web_search` tool; otherwise it gets `web_search` served by the chosen engine. `web_fetch`,
   `web_fetch_pdf`, and the PDF tools are always there. **Fallbacks:** native exists only when the
   researcher's model is ChatGPT, so Native on Claude Code uses Tavily, else Brave, else LH's
   "not available" tool text. A picked engine whose key is gone uses the other keyed engine, else
   native on ChatGPT, else the "not available" text; Settings shows the saved pick with
   "key missing, using …".
5. **Researcher prompt variant when native search is in use:** step 2's "Search with web_search using varied
   angles:" becomes "Search the web using varied angles:", and the paragraph "If web_search reports
   that search is unavailable because credentials are missing, … Never invent search results or
   sources." is left out. Everything else is verbatim; on Claude Code the prompt is verbatim.
6. **Jobs tab in the right panel** (beside Plan): LH's Background agents rows
   (`components/activity-dock.tsx:324-480`) for the open session's computing jobs only: kind,
   activity line, elapsed, cost label, inline detail, End; header total. Empty means empty.
   Extractions join in M9. With today's two providers the cost label is LH's `planCostLabel`:
   "ChatGPT" for ChatGPT jobs, "—" for unpriced Claude Code (`src/server/pricing.ts:16`).
7. **The invert switch persists in a side table.** `artifact_views` (entry id → inverted), written
   by a silent route, returned with the session detail, never sent to the model, deleted with the
   session. Replaces LH's in-place rewrite of `details.ui.inverted` (`setSteerUiInverted`,
   `src/core/contracts/jobs.ts:315`); the entry log stays append-only.
8. **Tool switches:** LH's four switches (research, demo, visual, pdf; default on; a switched-off
   tool is absent from the agent's tools), read fresh per turn.
9. **Worker request admission:** `WorkerAdmission`, an app-wide FIFO gate on concurrent worker
   model requests, default 8 (`src/agent/worker-request-admission.ts`), with LH's "Concurrent
   worker requests" number field (empty = default, positive whole numbers, LH's error text).
10. **Settings → Tools** is a new section with three cards: Background tools (decisions 8 and 9),
    Research (decisions 3 and 4), Demo browser (decisions 11 and 12). Lesson keeps Quizzing, File access,
    and Compaction limit.
11. **Demo browser search:** the setting, else on PATH `chromium`, `chromium-browser`,
    `google-chrome-stable`, `google-chrome` in that order, else the downloaded copy. Other
    Chromium-family browsers only through the setting.
12. **"Download Chromium for demos"** installs Playwright's `chromium-headless-shell` into
    `<data dir>/browsers` through the bundled Playwright driver. It ranks last (setting → PATH →
    downloaded). Settings shows progress and failure like the Claude Code download; the button
    hides once any browser is found.
13. **No browser:** `demo` still dispatches and fails at once, as in LH
    (`src/agent/subagents/demo-builder.ts:190-192`), with the text: "No render engine available: no
    Chromium-family browser was found. Set one in Settings → Tools → Demo browser, install
    Chromium, or use “Download Chromium for demos” there. (Verification is mandatory — demos are
    never delivered untested.)"
14. **Demo CSP:** the app CSP adds `'unsafe-inline'` and `https:` to `script-src`, `style-src`,
    `img-src`, `font-src`, and `connect-src`, matching LH's "any CDN" demo-builder prompt. The
    sandbox without `allow-same-origin` and the token check still protect the API.
15. **Delete removes unreferenced image files:** deleting a session removes its image files that
    no remaining session's entries or jobs reference, in the same step as the job cleanup.

## Flagged

- **LH has no native search.** Decisions 4 and 5 are our own. LH's engine pin never falls back
  when its key is missing (`src/server/search.ts:9-14`); ours does (decision 4). Neither falls back
  on a search error.
- **The status.md open question "M6 compaction vs. the append-only log"** is settled by M6's
  decision 1 (the marker is appended; entries saved meanwhile stay in the kept tail). For jobs it
  means: a wake is refused with 409 while a compaction runs, so job markers are never appended
  during a summary. The wake waits and fires after `compaction-changed` (running: false).
- **LH's sidebar Background agents section is app-wide**; ours is per session in the right panel
  (decision 6, a layout change).
- **Composer steers are memory-only, as in LH** (`src/server/jobs.ts:318-325`): a restart drops a
  parked steer, and the turn it rode dies with it anyway.
- **Worker requests are background requests** (LH `src/server/chat-handler.ts:168` builds role
  engines with `background = true`). The job runner asks `ProviderPolicy.admit("background")` at
  job start; a refusal ends the job with the kind's failure result, as LH's lease refusal does.

## Not in M7

| Left out | Comes with |
|---|---|
| Composer paperclip / drag-and-drop file path chips | not scheduled (decision 2) |
| Extractor and auditor (not jobs) | M9 |
| Side-chat updates through the context-update step | M8 |
| Activity dock, app-wide activity, priced cost for API keys | M11 |
| LH's Exa, Firecrawl, Ollama search | not ported |
| Plugin jobs | not ported (plugins are deferred) |

## Tasks

Group 1 tasks run concurrently, each on its own branch and T3 worktree off `main`. Group 2 runs
after M6 merges: T4, then T5 on T4, in one branch's worktree, one after the other.

### Group 1: no session core (start now)

#### T1. The workers as standalone modules (`m7-t1-workers`, backend)

**M6 dependency: none.** Each worker is a plain async function: input, a Pydantic AI `Model`,
callbacks for activity and usage, a cancellation path → its result model. No jobs table, no
delivery; T4 wires them into the runner.

- **Contracts** (`jobs/contracts.py`, LH `src/core/contracts/jobs.ts`): `ResearchInput`,
  `DemoInput`, `VisualInput`, `PdfInput`; `ResearchResult` (`brief`, `sources`), `PdfResult`
  (`path`, `question`, `brief`, `pages_read`, `pages_consulted`), `VisualResult` (`svg`, `notes`,
  `image`), `DemoResult` (`title`, `html`, `tested`, `notes`); `is_failure` (`:330-350`),
  `steer_text` and `abort_text` **verbatim** (`:372-405`, `:446-457`), `job_failure_text`
  (`:432`), `is_web_source_url`, `parse_sources` (`runner.ts:560-588`), `activity_line`.
- **Search** (`jobs/workers/search.py`, LH `src/server/search.ts`, `src/core/search.ts`): Tavily
  and Brave clients (httpx, LH's endpoints, headers, limits, 30 s timeouts, error texts), each
  given its key; `choose_search(setting, provider kind, keys)` returns native, Tavily, Brave, or
  none with decision 4's fallbacks. Key storage is T2's; T4 passes the keys in.
- **Web tools** (`jobs/workers/web.py`, LH `src/agent/tools/web.ts`, `safe-fetch.ts`,
  `pdf-read.ts`): `web_search`, `web_fetch` (LH's private-address guard, 5 MB cap, 40,000-character
  truncation, HTML to text), `web_fetch_pdf` (25 MB), and `pdf_info` / `pdf_extract` / `pdf_search`
  scoped to a per-job temporary directory removed afterwards. Names, schemas, descriptions, and
  texts verbatim.
- **Researcher** (`jobs/workers/research.py`, LH `subagents/researcher.ts`, `runner.ts:233-299`):
  `INSTRUCTIONS` verbatim; the native-search variant (decisions 4 and 5) when `choose_search`
  returns native; the prompt LH builds from question and context; sources from the brief's links,
  else fetched URLs; LH's failure briefs.
- **PDF reader** (`jobs/workers/pdf.py`, LH `subagents/pdf-reader.ts`, `pdf-ops.ts`,
  `pdf-markdown.ts`) with pypdfium2: triage, `pdf_info`, `pdf_extract`, `pdf_search`, `pdf_render`
  (page images go only to the reader, never to the teacher), `MAX_ITERATIONS = 14`, the learner
  file-access policy for the path, LH's prompt and failure briefs. CPU work runs in a thread.
- **Visual maker** (`jobs/workers/visual.py`, LH `subagents/visual-maker.ts`,
  `annotation-svg.ts`): `write_svg`, `edit_svg`, `render_svg` (resvg-py in a thread, the render
  returned as an image the model looks at), the annotation path over a learner image with LH's
  placeholder, LH's prompt and failure notes.
- **Demo builder** (`jobs/workers/demo.py`, `headless.py`, LH `subagents/demo-builder.ts`,
  `headless.ts`): `write_demo`, `run_demo` (Playwright with a given Chromium executable, headless:
  console errors, uncaught errors, failed requests, the optional `probe` via `evaluate()`, 2 s
  settle), at most 24 steps, the final verification gate, LH's prompt and failure notes. Without an
  executable it returns decision 13's failure.
- **Fake model:** `ScriptReply.role` (optional). A reply with a role is consumed only by requests
  of that model role, so worker scripts don't interleave with the teacher's.
- **Self-check:** `verstehen --self-check` also runs one offline headless page with the found
  browser when one exists, and renders an SVG and a PDF page as today.
- **Tests (offline, `FunctionModel`, temporary data dir, no network: httpx mock transport, local
  HTML files):**
  - each steer, abort, and failure text matches LH's;
  - sources come from cited links first, fall back to fetched http(s) URLs, at most 10;
  - each setting and model picks the right search, including every decision 4 fallback;
  - no search gives LH's text;
  - with native search the researcher has no `web_search` and gets the prompt variant;
  - `web_fetch` refuses private addresses and truncates long pages;
  - the PDF reader cites pages and counts only read pages in `pages_read`;
  - the visual maker renders, looks, revises, and fails with an empty `svg`;
  - an annotation keeps the learner-image placeholder;
  - the demo builder's verification gate rejects a demo with console errors (Playwright's
    Chromium on Pixal);
  - no browser gives decision 13's text;

#### T2. Settings → Tools (`m7-t2-tools-settings`, backend + UI)

**M6 dependency: none.** M6 adds `compaction_limit` to the same `Settings` model; the rebase
conflict is one line. The switches and the concurrency value take effect in T4.

- **Settings fields:** `tools: {research, demo, visual, pdf}` (each default true),
  `worker_request_concurrency: int | None` (LH's sanitize: positive safe integer, else default),
  `demo_browser: str | None`, `search_engine: "native" | "tavily" | "brave"` (default native).
- **Demo browser** (`jobs/workers/browser.py`): `find_demo_browser()` → path and source
  (`setting`, `path`, `downloaded`, or none) per decision 11; `BrowserDownloadService`
  (decision 12): start, progress, failure, cancel on shutdown, `PLAYWRIGHT_BROWSERS_PATH` set to
  `<data dir>/browsers`. Routes `GET /api/demo-browser`, `POST /api/demo-browser/download`,
  `GET /api/demo-browser/download`, modeled on the Claude Code download routes.
- **Credentials file:** the ChatGPT `CredentialsStore` file handling moves to
  `providers/credentials.py`, shared by ChatGPT and a `search_keys` section; one lock, the same
  atomic 0600 write. ChatGPT behavior is unchanged. `search_keys()` returns each engine's key,
  env first (decision 3).
- **Search key routes:** `GET /api/search-keys` (per engine: present, masked, source
  env/file/none, and the engine research would use now), `PUT` and `DELETE
  /api/search-keys/{engine}`. Env-sourced keys are read-only.
- **UI (`settings-tools.svelte`):** Background tools card (four switches with LH's labels, the
  concurrency field committing on blur or Enter, LH's error text); Research card (the Search engine
  select with Tavily and Brave disabled until keyed and the "key missing, using …" note; masked
  fields, set and clear, LH's docs links, "from environment" when env wins); Demo browser card (path field
  that commits on blur or Enter, the found browser and its source, the download button with
  progress and failure, hidden once a browser is found).
- Regenerate API types.
- **Tests:** settings defaults and sanitizing; PATH order and the setting override; the downloaded
  copy ranks last; download success, failure, and progress (fake driver); masked keys never
  return the value; env keys win and can't be cleared; search keys are saved 0600 beside
  ChatGPT credentials without changing them. Vitest: the concurrency field's empty, invalid, and
  commit cases; the download button's states.

#### T3. Learner images (`m7-t3-images`, backend + UI)

**M6 dependency: none.** One wiring line in `TurnService.build_agent` adds the tool to the
teacher; that is the only `session/` edit in group 1.

- **Loading** (`teaching/images.py`, LH `src/agent/tools/learner-image.ts`,
  `learner-image-dimensions.ts`): `check_learner_image(path)` and `load_learner_image(path)`
  through the learner file-access policy; regular files only, at most 25 MiB, 16,000,000 pixels,
  8,192 px per side; jpg, png, gif, webp, bmp; normalized to an upright, metadata-free PNG or JPEG
  with Pillow (in a thread); saved with M5's `save_attachment`. LH's error texts.
- **`show_image`** (LH `src/agent/tools/show-image.ts`): teacher only, always on; schema and
  description verbatim; result text "Shown to the learner: <path> (<w>×<h>)."; `details` = path,
  caption, mime type, sha256, width, height. The image is never sent back to the model.
- **Route:** `GET /api/images/{sha256}.{ext}` serves a stored image (token-checked; the UI fetches
  it and shows an object URL).
- **UI:** the image card for `show_image` results (LH `components/artifacts/image-card.tsx`): the
  picture, caption, and path.
- **Tests:** size, pixel, side, and format limits with LH's texts; EXIF rotation applied and
  metadata removed; protected paths refused; `show_image` returns text only and its details; the
  route serves only stored hashes. Vitest: the image card. Verify flow `show-image`.

### Group 2: jobs in the session (after M6 merges into `main`, rebased on it)

#### T4. Jobs, delivery, and wakes (`m7-jobs`, backend)

**M6 dependency: full.** Starts from `main` with M6 merged; extends the M6 functions listed
below.

- **Tables** (next free migration number at rebase time): `jobs` (id, session id, kind,
  tool call id unique per session, input, status running/done/error, activity, result, error,
  delivery kind result/abort/failure, delivery status pending/delivered, usage, created/updated),
  `artifact_views` (entry id, inverted). `store/jobs.py` (`JobsStore`), `store/artifact_views.py`.
- **Job tools** (`jobs/tools.py`, LH `src/agent/tools/jobs.ts`): `research`, `demo`, `visual`,
  `pdf` with schemas, descriptions, and acknowledgements verbatim. `dispatch` finds or creates the
  job by tool call id with its input, starts the runner without waiting, and returns
  "Dispatched (job <id>). <ack>". `visual` with `image` and `pdf` check the path first and fail
  the call. The prober gets `research` and `pdf`, the teacher all four, each only when its switch
  is on (decision 8).
- **`JobRunner`** (`jobs/runner.py`, LH `subagents/runner.ts`): per kind, resolve the role's model
  fresh (`researcher`, `demoBuilder`, `visualMaker`, `pdfReader`), ask
  `ProviderPolicy.admit("background")`, run T1's worker through `WorkerAdmission`, write activity
  and usage (usage table rows with the role), and on completion save result, status, and pending
  delivery in **one** update, then call the injected `wake_session(session_id)`. Refusals and
  crashes end with LH's failure shapes. Abort (`POST /api/jobs/{id}/abort`, LH
  `src/server/jobs.ts:407-425`): 404 / 409 as LH, else error "Aborted by learner", pending abort
  delivery, cancel the task. Annotated photos save their snapshot through T3.
- **Delivery** (`session/delivery.py`, on `SessionRuntime`): one queue of pending job markers
  (`subagent-steer`, `subagent-abort`, ids `steer_<job id>`) and one of composer steers. **The
  context-update step** runs before every model request (Pydantic AI `before_model_request` /
  history processor) with two named kinds: `job_result` (only when `ProviderPolicy` admits
  background for the account, never while the response it would follow holds a pending question)
  and `composer_steer` (learner input, always). Injected entries are saved with the turn's
  entries; their jobs are marked delivered **in the same transaction**. Markers handed to a run
  that ended on a question stay pending and ride the next run's first model call.
- **Idle wake** (`wake_session`, wired in `verstehen/app.py`): when no turn runs, no compaction
  runs, no question is pending, the log doesn't end in a dismissal or a question-recovery request,
  and `ProviderPolicy` admits background, start a turn with input `steers` whose write-ahead
  appends are all pending job markers. Otherwise wait: the pump re-runs on `turn-settled`, on
  `compaction-changed` (running: false), on an answer saved without a turn, and on account or
  consent changes. A 409 retries on the next of those events; a 403 waits for consent. No polling
  and no `GRACE_MS`: the 2026-11-18 race decision applies (a test reproduces LH's race).
- **Composer steers:** `POST /api/sessions/{id}/steer` `{id, text}` queues the text for the live
  run (409 when no turn runs, so the UI sends normally); saved as a user entry with the client id
  when delivered (LH `src/server/jobs.ts:281-325`).
- **`continue` purpose:** a continuation whose request cause is automatic (the last input was a
  job marker or the handoff) is a background request (LH `reconstructRequestCause`,
  `src/core/native-messages.ts:989`).
- **Recovery** (LH `recoverStaleJobs`, `src/server/jobs.ts:719-755`): `GET /api/jobs?session=…`
  returns the session's jobs and runs a sweep at most every 30 s: pending deliveries are queued and
  pumped; a `running` job without a live worker is re-run; sessions with a running turn are
  skipped; jobs without delivery state are left alone.
- **Delete** (LH `src/server/chats.ts:72-95`): refused with 409 `jobs_running` and LH's text while
  a job computes; otherwise the session's jobs, artifact views, and queues go with it, and
  unreferenced image files are removed (decision 15).
- **Events:** `jobs-changed` on `/api/events` at every job write.
- **Routes:** jobs list and abort, steer, artifact view (silent PUT), session detail with
  artifact views. Regenerate API types.
- **M6 functions T4 extends:**

  | M6 function | M7 change |
  |---|---|
  | `TurnService.compaction_gate` | the `steers` wake input passes the gate with its appends |
  | `TurnService.claim_and_write_ahead` | its 409 while compacting makes the wake wait for `compaction-changed` |
  | `TurnService.settle` | saves delivered job ids with the entries; after M6's `kick` and the owed handoff, pumps pending deliveries |
  | `CompactionService.compact` / `kick` | on finishing, the runtime's event re-runs the delivery pump |
  | `SessionRuntime.compaction` | read by the wake conditions |
  | `serialize_for_summary` | job markers as `[SYSTEM NOTE] <content>` (LH `src/core/compaction.ts:361`); `show_image` results as text only |
  | `compaction_cut_index` | job markers are valid cut points, as LH custom messages (`:237`) |
  | `estimate_entry_tokens` | job markers count their content |
  | tail readers (`tail_ignoring_display_markers`, `needs_continuation`, `failed_response_at_end`, `retry_drops`) | job markers are model-visible input, not display markers; checked against LH `failedTail` (`src/core/input-events.ts:440-449`) |
  | `to_llm_messages` | job markers become user text with their content |

- **Tests (offline, `FunctionModel`, temporary data dir), named after the behavior:**
  - a job tool returns the acknowledgement at once and the turn continues;
  - a repeated tool call id creates no second job;
  - a switched-off tool is absent; the prober has only `research` and `pdf`;
  - result, status, and pending delivery are saved together;
  - a result during a running turn is injected before the next model call and saved once;
  - a result while a question is pending waits and rides the answer turn's first model call;
  - an idle result starts a wake turn with every pending marker;
  - a wake never starts during a compaction, a dismissal pause, or a recovery request;
  - LH's answer race: an answer and a wake collide, the answer wins and carries the markers;
  - background refusal leaves the result pending and injects nothing;
  - a delivered marker marks its job delivered in the same transaction;
  - abort delivers the abort marker; a finished job can't be aborted;
  - a worker failure still delivers its failure text;
  - recovery re-queues pending deliveries and re-runs orphaned workers, at most every 30 s;
  - a composer steer is injected at the next model request; with no turn it is refused with 409;
  - a stranded composer steer rides the next run;
  - delete is refused while a job computes, and removes jobs, views, and unreferenced images;
  - worker requests wait in the FIFO gate beyond the concurrency limit;
  - compaction serializes job markers as system notes and may cut at them.

#### T5. Jobs UI (`m7-jobs`, on T4)

**M6 dependency: full** (the thread already draws M6's dividers and compacting state).
Behavior ported exactly; the look follows our design. Svelte 5 runes only.

- **Jobs feed** (LH `components/chat.tsx:1372-1440`): fetch `/api/jobs?session=…` on mount, on
  `jobs-changed` (250 ms trailing debounce), and on resync; a settled job syncs the session (or
  adopts append-only while a turn streams).
- **Thread cards** (LH `components/artifacts/`): the dispatch card for each job tool call with its
  live activity, then the quiet one-liner (`dispatch-card.tsx`, `job-card.tsx`); job markers as
  cards, never bubbles (`steer-card.tsx`): research brief with sources, PDF brief with the pages
  badge, the visual card (SVG, annotated photo, invert switch hidden for photos), the demo card
  (`<iframe sandbox="allow-scripts" srcdoc>`, invert switch), abort and failure cards. The invert
  switch writes decision 7's view.
- **Jobs tab** in the right panel (decision 6), with End and LH's abort states.
- **Composer steering** (LH `components/composer.tsx:33-40`, `chat.tsx:1556-1582`): while a turn
  runs, Enter or Send with text steers; the queued-steer lines above the composer until the steer
  lands; the placeholder "Ask, answer, or steer the lesson…"; a 409 falls back to a normal send.
- **Delete dialog:** LH's `jobs_running` error line with Try again.
- **CSP:** decision 14 in `app/src-tauri/tauri.conf.json`.
- **Tests (Vitest):** the dispatch card follows the feed by tool call id; marker cards by kind;
  the invert switch persists; Jobs tab rows and End states; steer versus send while running; the
  queued-steer indicator clears when the steer lands.

## Verify flows (fake model)

| Flow | Task | Shows |
|---|---|---|
| `settings-tools` (dark/light) | T2 | switches, concurrency field errors, search engine select, masked keys, demo browser found and download states |
| `show-image` | T3 | `show_image` result card with caption |
| `job-research-live` (dark/light) | T5 | dispatch card with activity → result injected mid-turn → research card with sources; Jobs tab row disappears |
| `job-idle-wake` | T5 | the turn ends, the result arrives later, the wake turn streams by itself |
| `job-behind-question` | T5 | the result waits behind a quiz and arrives with the answer turn |
| `job-demo` | T5 | tested demo in the sandboxed iframe, invert switch kept after reload |
| `job-visual-annotate` | T5 | figure card and annotated photo card |
| `job-abort` | T5 | End in the Jobs tab → abort card → the teacher acknowledges |
| `job-recovery-reload` | T5 | reload after a sidecar restart with a pending result → it arrives |
| `composer-steer` | T5 | a message sent mid-turn shows as queued, then lands in the same run |
| `delete-jobs-running` | T5 | delete refused while a job computes, Try again succeeds after it ends |

Worker replies use `ScriptReply.role` (T1). `make verify-live` stays as it is.

## Feature map entries

Settings → Tools (background tools, research keys, demo browser); `show_image`; job tools and
dispatch cards; job result cards (research, PDF, visual, annotated photo, demo with invert); Jobs
tab with End; idle wakes and delivery behind questions; composer steering; job recovery; delete
with running jobs.

## Open questions

None.
