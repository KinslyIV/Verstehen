# Desktop responsiveness

Show the desktop shell while the local backend starts. Load saved model choices before
provider discovery, keep the picker steady across tabs and accounts, and give Settings a
picker for each slot. Serve session and graph summaries without decoding unrelated
transcripts. Add a per-fragment prompt editor over the existing override files and switches.
The overview was approved in the task thread on 2026-11-23.

## Baseline

Starting revision: `e7329c6` on `dev`. On Pixal, the Python source sidecar answered its
first health check after 8.1 s against a new database and 3.5 s on a second launch. With
80 synthetic teaching sessions and 0, 100, and 500 entries per session, median
`GET /api/sessions` time was 14, 78, and 366 ms respectively over five requests per
configuration. The sidebar payload stayed around 14 KB. The packaged Arch first paint and
canvas frame times need their own measurements.

## Startup and models

- Tauri shell and frontend API connection: show the window before the sidecar is ready;
  surface a terminal startup failure, and keep the authenticated readiness handshake.
  Measure window, sidecar, and usable composer separately on packaged desktop where available.
- Provider adapters and model controls: load saved slots and last successful per-account
  catalogs locally; let slow accounts finish independently and expose explicit refresh.
  Keep credentials out of persisted catalog data. Invalidate correctly on account removal
  or replacement. Keep live dispatch and selection validation at their existing boundaries.
- Composer model menu and Settings Models: use stable popover dimensions, scroll long
  columns inside the popup, and make each Settings row operate on its own slot. Reuse model
  selection rules. LearnHarness 0.7.0 uses a manual refresh and persisted catalog
  ([change](https://github.com/amosblomqvist/learnharness/commit/1cfb7ea2d)).
- Test empty, saved, slow, offline, and changed-account states with offline responses.
  Extend `model-menu`, `settings`, and shell coverage as appropriate, with feature-map entries.

## Sessions

- Session store, service, routes, and sidebar: read summaries and pending indicators without
  decoding each transcript. Refresh the affected row on session notifications and preserve
  ordering, removal, and recovery after stream reconnect. Prefer the current schema.
- Session controller and coverage service: compute initial coverage using the already-read
  entries and use a small coverage response for subsequent updates. Rebenchmark the
  baseline and profile long-session opening and streaming. LearnHarness 0.7.0 shipped
  [transcript-free stats](https://github.com/amosblomqvist/learnharness/commit/3077538c);
  its [virtualization PR](https://github.com/amosblomqvist/learnharness/pull/704) is a
  follow-up reference when measurements support that work.
- Test historical open and dismissed questions and practice problems, list refresh and
  reconnect, and coverage refresh. Extend existing session, practice, and coverage flows
  and the feature map as needed.

## Graph

- Graph stores, service, and page controller: remove the duplicate full session-list
  request and narrow title and cost reads. Keep independently available graph data usable
  while ancillary requests finish.
- Canvas: defer force simulation until a node interaction or physics change needs it and
  remove temporary projected node collections from hit testing. Profile zoom and pan on a
  large synthetic graph and reproduce the reported click issue before changing selection
  behavior. Reference [LearnHarness PR #879](https://github.com/amosblomqvist/learnharness/pull/879).
- Test hit ordering, hidden nodes, drag, and physics behavior. Extend `graph-canvas` with
  representative zoom and selection coverage and update the feature map.

## Prompt settings

- Settings, prompt API, and prompt composition: expose each supported fragment's default
  and override, edit and preview, save and activate, enable or disable, and delete an
  override. Use the existing prompt switches and approved override paths. Coordinate writes
  with existing prompt sync, including failures and reload. Follow the shipped
  [LearnHarness 0.7.0 editor](https://github.com/amosblomqvist/learnharness/commit/53f923872).
- Test default and override resolution, errors, save and delete, and synchronization with
  temporary data. Add a prompt Settings flow and its feature-map entry.

## Integration

Use isolated implementer worktrees for startup/models, sessions, and graph, followed by
prompts when a slot opens. Integrate on `desktop-responsiveness`, regenerate the API client
types, and reconcile feature-map entries and area docs. Document deliberate differences
and any implementation decisions for review.

Implementers target specific tests while editing, run the required area-scoped commit checks,
and name only affected browser flows with `FLOW=`. Reuse a valid build with
`make verify-run`. On Pixal, run one heavy verification or packaging job at a time. Report
required runs still pending so they can be scheduled without overlap. The integration
branch runs the full checks, browser suite, and live smoke before the PR. Inspect the
scripted screenshots and attach evidence to the PR into `dev`.
