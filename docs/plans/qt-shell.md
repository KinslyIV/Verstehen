# Qt Shell — PySide6 + QtWebEngine replaces Tauri

> Status: **approved by the user (2026-11-24).**
> Branch: `qt-shell` off `dev`.

## Overview

- **What changes:**
  1. **Desktop shell:** `app/src-tauri/` (Rust, Cargo, `tauri.conf.json`), the `@tauri-apps/*`
     npm packages, and Rust in the Arch build image are removed. A new `verstehen.desktop` package
     runs a PySide6 `QWebEngineView` window on the main thread and uvicorn + FastAPI on a background
     thread, **in one process**. FastAPI serves the built SPA in desktop mode, so page and API share
     one origin; the per-launch token is an **HttpOnly, SameSite=Strict cookie** the shell puts in
     the window's cookie store.
  2. **Demo checks on the desktop** run in a hidden `QWebEnginePage` inside the app's Chromium
     (`DesktopDemoRunner`); server mode keeps Playwright. On the desktop, Playwright, the Chromium
     lookup and download, and Settings → Tools → Demo browser are removed.
  3. **WebKitGTK workarounds removed**, each checked in the Qt build.
  4. **Transcript on Chromium:** `content-visibility` placeholders for off-screen rows return
     (revert `8048135`); demo iframes load only near the viewport and unload when far away.
  5. **Checks:** memory before/after and one session-retention check with a Chromium heap snapshot.
- **Structure afterwards:**
  ```
  verstehen (one process, PyInstaller onedir)
  ├─ main thread: DesktopShell — QWebEngineView ──loads──▶ http://127.0.0.1:<port>/
  │     cookie store: verstehen_token (HttpOnly, SameSite=Strict)
  │     opens the two allowed external URLs with QDesktopServices
  │     DesktopDemoRunner: hidden QWebEnginePage per check, off-the-record profile
  └─ server thread: uvicorn + FastAPI — /api + the built SPA (desktop mode only)
        └─ services, jobs, SQLite (unchanged)
  verstehen --server → headless server, never imports Qt; demo checks via Playwright
  ```
- **What the user notices:** the app runs on Chromium, so the WebKitGTK bugs (buttons, scroll
  jumps, wheel stalling over demos, native pinch magnification) go away; long lessons open faster;
  a demo scrolled far away resets when it comes back; no Demo browser setting on the laptop; the
  package grows by roughly 150–250 MB. A backend crash closes the whole app (data is safe).
- **Non-obvious effects:** no saved-data change or migration. Android (Capacitor), server mode,
  sync, and the SSH provisioner are unchanged apart from dropping the Tauri CORS origins.
  PySide6 is a `desktop` extra: the server bundle's `requirements.txt` never contains it, and
  Playwright moves to the server side. `make verify` keeps running in Playwright's Chromium.

## User decisions

- **Shell:** PySide6 directly (not pywebview).
- **Process:** one process — Qt on the main thread, uvicorn on a background thread.
- **Page origin:** FastAPI serves the built SPA in desktop mode (same origin, no CORS).
- **Token:** HttpOnly, SameSite=Strict cookie set by the shell; the backend checks it in desktop
  mode; the frontend drops its desktop token code.
- **Naming:** package `verstehen.desktop`; `DesktopShell`, `DesktopDemoRunner`; entry
  `verstehen desktop` / `python -m verstehen.desktop`; the frozen `/usr/bin/verstehen` opens it.
- **Demo checks:** QtWebEngine on the desktop; Playwright in server mode; both return
  `DemoRunResult`.
- **Desktop Playwright and Demo browser setting:** removed on the desktop, kept in server mode.
- **WebKitGTK workarounds:** removed in this plan.
- **Off-screen rows:** restore `content-visibility` placeholders (difference from LearnHarness).
- **Demo iframes:** load near the viewport, unload far off-screen (difference from LearnHarness);
  a zoomed demo is never unloaded.
- **Retention:** one check after the switch (PSS across session switches + heap snapshot).

## Tasks (commit order)

### 0. Plan, decisions, baseline (orchestrator)
- `docs/plans/qt-shell.md`, `docs/decisions.md` (the decisions above until implemented; the three
  LearnHarness differences permanently).
- Baseline memory on the laptop, Tauri build, same method as below: PSS per process with a
  demo-free lesson open (measured 2026-11-24: web 380 MB, sidecar 142, shell 111, network 34;
  ~667 MB), and after opening a 2-demo session (web 458 MB).

### 1. Backend: desktop mode serves the SPA and accepts the cookie
- `config.py`: desktop mode no longer requires `VERSTEHEN_TOKEN` from the environment when the
  shell passes it in-process; keep the ≥64-character rule. `app.py`: in desktop mode mount the
  built SPA (`adapter-static` output, `index.html` fallback for client routes) after `/api`, send
  the CSP the Tauri config set (minus `ipc:`/`tauri` entries; `script-src 'unsafe-inline' https:`
  stays so `srcdoc` demos run), check the token from the `verstehen_token` cookie (constant time)
  or the existing header, and drop every Tauri CORS origin (desktop and server mode).
- `cli.py`: split `serve` so the shell can start uvicorn on a thread with an injected listener and
  stop it cleanly; the stdin-EOF watcher stays for nothing else and is removed.
- Tests (`backend/tests/shell/`): SPA routes and fallback served only in desktop mode; cookie
  accepted, missing/wrong cookie refused; header still accepted; server-mode CORS without Tauri.
- Scoped check: `make check AREA='shell'`.

### 2. `verstehen.desktop`: the window, server thread, and shutdown
- New `backend/src/verstehen/desktop/` (`__main__.py`, `shell.py`): `DesktopShell` creates the
  window at once (starting screen), picks a port, generates the token, starts the server thread,
  waits for `/api/health`, sets the cookie in `QWebEngineProfile.cookieStore()`, loads the page;
  on close stops uvicorn, then exits. Startup failure (30 s or server error) shows the existing
  failure text with the log path. External links: `acceptNavigationRequest` /
  `createWindow` open only the two allowed URLs (`auth.openai.com`, the Claude Code setup page)
  via `QDesktopServices`; nothing else leaves the window. Drag-drop of files onto the window does
  not navigate. DevTools only with `VERSTEHEN_DEVTOOLS=1`.
- `cli.py`: `verstehen desktop` subcommand. import-linter: `desktop` sits left of `api`; ruff bans
  `PySide6` outside `desktop/`.
- `pyproject.toml`: `desktop` extra (`PySide6-Essentials` + `PySide6-Addons` WebEngine as needed);
  Playwright moves to a `server` extra used by the server bundle and dev.
- Tests: `FunctionModel`-free unit tests for the navigation allowlist and startup state; a
  `pytest-qt`-style offscreen smoke (`QT_QPA_PLATFORM=offscreen`) marked `slow`.
- Scoped check: `make check AREA='shell'`.

### 3. Frontend: drop Tauri
- Remove `@tauri-apps/api` and `@tauri-apps/cli`; `connection.svelte.ts` becomes base `''` with
  no lookup in desktop mode (the shell already waited for health); `startup.ts` timing marks go
  to a small `POST /api/startup-mark` or are dropped if `startup_mark` has no remaining reader
  (orchestrator decides; record it); `client.ts:402` opens external URLs with `window.open`,
  which the shell routes to `QDesktopServices`. Delete `tauri-config.test.ts`; update
  `client.test.ts`, `connection.svelte.test.ts`.
- Scoped check: `make check AREA='shell'`, `make verify FLOW='health settings'`.

### 4. Demo checks: `DesktopDemoRunner` on the desktop, Playwright on the server
- `jobs/workers/headless.py`: a `DemoRunner` protocol returning `DemoRunResult`; the Playwright
  implementation stays as is for server mode. `desktop/demo_runner.py`: hidden `QWebEnginePage`
  per check in an off-the-record profile, called from the server thread through a Qt-thread bridge
  (queued signal + `asyncio` future). Console errors and uncaught errors from
  `javaScriptConsoleMessage`; disallowed schemes blocked by a `QWebEngineUrlRequestInterceptor`;
  failed requests from `loadFinished` plus an injected listener for resource `error` events; the
  demo served through a custom scheme handler (no 2 MB `setHtml` limit); 30 s load timeout, 2 s
  settle, probe via `runJavaScript`. `app.py` wires the runner by mode.
- Desktop mode: no `find_demo_browser`, no `BrowserDownloadService`, no Demo browser routes in
  `api/tools.py`; `settings-tools.svelte` hides Demo browser and the download button in desktop
  mode. `self_check.py` tests a Qt demo page in the desktop bundle, Playwright in the server bundle.
- Tests: shared contract fixtures (`backend/tests/fixtures/workers/`) run against both runners —
  same `DemoRunResult` for a clean demo, a console error, an uncaught error, a blocked scheme, a
  failed request, a probe value, a demo over 2 MB. Spec:
  [subagents and background work](../learnharness/subagents-and-background-work.md).
- Scoped check: `make check AREA='jobs shell'`, `make verify FLOW='job-demo settings'`.

### 5. Packaging
- `backend/packaging/verstehen-sidecar.spec` → `verstehen.spec`: one onedir app with PySide6 and
  QtWebEngine (`QtWebEngineProcess`, resources, locales); entry `verstehen.desktop`. Server
  bundle: `requirements.txt` from the `server` extra; a check fails if it contains `PySide6`.
- `packaging/`: drop Cargo/Rust from `Dockerfile`, `build.sh`, `compile.sh`, `container.sh`;
  `PKGBUILD` installs the onedir app, `depends` drops `webkit2gtk-4.1`/`gtk3` for the Qt runtime
  libraries the bundle needs (`libxkbcommon`, `nss`, `fontconfig`, …, settled by the smoke test);
  `smoke.py` rewritten: the app starts offscreen, serves `/` and `/api/health` with the cookie,
  refuses without it, runs migrations, a Qt demo check passes, and shutdown leaves no process.
- `docs/architecture/tooling.md` release notes: `app/src-tauri/*` version files go.
- Scoped check: `make check AREA='shell'`, then `make app`.

### 6. Remove WebKitGTK workarounds and restore Chromium behavior
- **Demo wheel forwarding** (`5bf28b3`, wheel part of `a0db6d0`): remove `demoWheel` from
  `jobs.ts`, the bridge script's wheel code, and the card's handler; update `job-demo.flow.ts`.
- **Drag-drop:** `source-drop.svelte.ts` in-memory fallback for hidden custom types, the
  `text/plain` duplicate in `source-drag-row.svelte`, `draggable={false}` on session links if it
  only served WebKitGTK — each removed only when the flow passes in Chromium and on the laptop.
- **Graph pinch:** the WebKitGTK native-magnification note in `graph.md` and the roadmap entry go
  once a trackpad pinch on the laptop reaches the graph's Ctrl+wheel zoom.
- **Off-screen rows:** revert `8048135` (`message-scroller-item.svelte`): `content-visibility:
  auto` placeholders, no `@supports` gate.
- **Kept:** the floating bottom block and `dock-wheel.ts` (LearnHarness layout, not a WebKit fix).
- Scoped check: `make check AREA='jobs graph shell session'`,
  `make verify FLOW='job-demo sidebar-folders graph-canvas thread-navigation question-collapse'`.

### 7. Demo iframes load near the viewport and unload far away
- `demo-card.svelte`: an `IntersectionObserver` (root margin about two viewport heights) mounts
  the `<iframe srcdoc>` only near the viewport and replaces it with a placeholder of the last
  measured height when it leaves that margin; a zoomed demo is never unloaded. The error banner
  and "Send to teacher" stay tied to the loaded frame.
- Tests: unit test for the mount/unload decision; `job-demo.flow.ts` checks a far demo is not
  loaded on open, loads when scrolled near, unloads after scrolling away with no transcript shift,
  and survives zoom. Feature-map entry.
- Scoped check: `make check AREA='jobs'`, `make verify FLOW='job-demo thread-navigation'`.

### 8. Memory and retention check (orchestrator, on the laptop)
- Same PSS method as the baseline with the Qt build: demo-free lesson, then the 2-demo session.
- Switch between two sessions five times, ending on the demo-free one, idle 2 minutes; take a
  heap snapshot in DevTools (`VERSTEHEN_DEVTOOLS=1`) and look for detached `SessionThread` /
  `SessionController` objects or iframes. Fix any retention found; otherwise record the numbers in
  the PR.

### 9. Docs sync, review rounds, full verification, PR into `dev`
- `docs/architecture.md`, `architecture/{tooling,frontend-shell,api-and-events,jobs,graph}.md`,
  `docs/roadmap.md`, `docs/decisions.md`, `docs/feature-map.md`, `docs/status.md`, `AGENTS.md`
  (Tauri + SvelteKit → PySide6 + SvelteKit).
- Review rounds per [workflow](../workflow.md); final `make check` and `make verify`; inspect
  screenshots; laptop install of `make app` with the user; push and open a PR into `dev`.
