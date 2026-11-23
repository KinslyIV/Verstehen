# Mobile & Sync — Milestone D: Android app, pairing, phone UI, and SSE recovery

> Status: **approved by the user (2026-11-23).** Part of
> [mobile-and-sync.md](mobile-and-sync.md). No LearnHarness counterpart for pairing or the phone
> layout; mouse behavior everywhere stays exactly as LearnHarness has it.

## Overview

D builds the Android app and makes the existing `app/` SPA comfortable on a phone. It ships as
two PRs into `dev`, in order (the former Milestone E is folded in; user decision, 2026-11-23):

1. **Android app and pairing:** remote mode, `/pair`, the Capacitor Android project, connection
   storage, the Android project with the Tailscale-only cleartext rule, `make android`, and the
   release job. After it, the user installs the `.apk`, pairs, and uses the desktop layout on the
   phone.
2. **Phone UI and recovery:** the layout, `/graph` touch, phone Settings, and reconnecting, each
   checked on the phone as it lands, alongside headless Chromium flows at the phone and tablet sizes.

- **Remote mode:** besides the desktop sidecar, the client can hold a server URL, device id, and
  device token, stored in the app's private storage on the phone. Missing config or a `401` routes to
  `/pair`, which redeems the server's 8-character code through the existing `POST /api/auth/pair`.
- **Phone and tablet layouts:** below 768 px (the breakpoint shadcn's sidebar already uses) a
  sidebar drawer and right-panel tabs as full-screen views; 768–1279 px a drawer with the lesson and
  a closable right panel side by side; 1280 px and up the desktop layout. Touch screens get
  touch-sized targets and `/graph` gestures at any width; safe-area insets, on-screen keyboard
  handling, and responsive Settings complete it.
- **Phone Settings:** the server's settings, with Models (the server's slots, C's leftover),
  read-only Accounts, File access hidden, and a Connection section in place of Sync.
- **Connection recovery:** one helper reconnects every stream on foreground and network return,
  refetches what the page shows, keeps a running turn attached through outages, and shows a quiet
  "Reconnecting…" line.

No backend changes are expected: pairing, device revocation, settings, and models already work in
server mode.

## User decisions

1. **Remote mode runs inside the app shell only.** D adds no web serving from the server. Real-phone
   use starts with PR 1's `.apk`; automated flows run at phone size in headless Chromium.
2. **Right panel on a phone: full-screen tab switcher.** A top bar holds a button per tab (Plan,
   Jobs, Side chat, Activity); a tab replaces the lesson full screen, and a Lesson control returns.
   Selection Ask and Ctrl+J open the Side chat screen.
3. **The phone layout starts below 768 px**, shared with the existing `IsMobile` hook; a narrow
   desktop window gets it too. Decision 11 adds the tablet layout above it.
4. **`/graph` touch: no node dragging.** Tap opens the node card, long-press opens the context menu,
   any one-finger drag pans, pinch zooms. Mouse input is unchanged. Recorded in `decisions.md`.
5. **Phone-adapted Settings:** Appearance, Lesson, Graph, and Tools as on desktop (applied to the
   server); Models shows the server's slots; Accounts is read-only with "Sign in from the laptop:
   Settings → Sync"; File access is hidden; Sync is replaced by Connection (server address, device
   name, Disconnect: best-effort revoke of this device on the server, forget the token, go to
   `/pair`).
6. **C's two deferred Settings → Sync races stay out of D**, on their own small branch.
7. **Connection recovery: wait, then reconnect.** On `visibilitychange`/`pageshow`/`online`, every
   stream reconnects and the page refetches; network failures back off without counting as
   failures; a running turn reattaches instead of showing "connection dropped" (server errors still
   fail as today); a quiet "Reconnecting…" line shows while disconnected. The same code runs on
   desktop.
8. **D and E merged, Android first** (2026-11-23): one milestone, two PRs, PR 1 the Android app and
   pairing, PR 2 the phone UI and recovery.
9. **Agents test on an Android emulator before the user** (2026-11-23): agents build, install, use,
   and screenshot the app on an emulator through T3 Code's Device panel (`agent-device`) on the
   user's Arch laptop (KVM, 14 GB RAM). The Android toolchain installs from the command line;
   Android Studio is optional and nothing depends on it.
10. **Debug builds also allow cleartext to `10.0.2.2`** (2026-11-23), the emulator's address for the
    host, so agents test against a local fake-model `--server` backend. The release `.apk` keeps
    only `100.64.0.0/10`, and a test checks that. Android's network security config cannot express
    a CIDR range, so a native WebView guard enforces it (decided during PR 1, see
    [decisions](../decisions.md#waiting-for-your-review)): the config allows cleartext, the guard
    blocks every `http://` request except `localhost`, `100.64.0.0/10`, and, in debug builds only,
    `10.0.2.2`; `/pair` also refuses other addresses.
11. **Phone and tablet layouts, sized to the user's devices** (2026-11-23): a Samsung Galaxy S24
    (360×780 CSS px) and a Galaxy Tab S9 (800×1280 portrait, 1280×800 landscape). Below 768 px the
    phone layout; 768–1279 the tablet layout (sidebar as a drawer, lesson and right panel side by
    side, the panel closable); 1280 and up the desktop layout. Touch sizing and `/graph` touch
    gestures follow the input type (`pointer: coarse`), not the width. Flows and emulator profiles
    use these sizes. This refines decision 3.
12. **One release signing key, created by the user** (2026-11-23): `make android-key` creates it
    outside the repository (e.g. `~/.config/verstehen/android-release.jks`) and prints the GitHub
    secrets to add; CI signs tagged releases with it and local `make android` uses it when
    present. Agents use only debug builds and never read the key or its password.
13. **The phone keeps its connection in a private file, not the Keystore** (2026-11-23): Capacitor's
    official Preferences plugin writes the server URL, device id, and token to the app's private
    storage, excluded from Android backup. This replaces the approved plan's Android Keystore
    storage; a rooted phone or backup tool could read the token, and revoking the device on the
    laptop is the remedy.
14. **The Android app uses Capacitor, not Tauri 2 Mobile** (2026-11-23): the phone app is
    client-only, so Tauri's Rust core brings nothing there. `app/src-tauri/` stays desktop-only and
    unchanged; Android needs no Rust or NDK. Official plugins: Preferences (connection), App
    (foreground and background), Keyboard. The WebView's own `fetch` keeps SSE streaming; Capacitor's
    native HTTP plugin is not used because it cannot stream. The page loads from
    `http://localhost`, which the server's CORS allowlist gains.

## Implementation details

Mode selection, verify transport, and `/pair` fields approved by the user on 2026-11-23.

- **Mode selection:** the desktop app keeps the sidecar; the Android app is always remote. The
  headless flows, which run in desktop Chromium, select remote mode with a build-time
  `PUBLIC_VERSTEHEN_CLIENT=remote` flag that normal builds never set.
- **Verify transport:** remote flows start the backend in `--server` mode and enter the preview's
  own `host:port` on `/pair`, which proxies `/api` to it, so no test-only CORS origin is added.
  Cross-origin access from the Android WebView is proven on the emulator and by PR 1's phone smoke test.
- **`/pair` fields:** server address (`100.x.y.z:port`, `http://` implied), the code (case-insensitive,
  8 characters), and a device name prefilled with "Phone", editable. A `401` later keeps the server
  address prefilled and drops only the token.
- **Indicator placement:** "Reconnecting…" sits at the top of the main column (below the phone top
  bar), never covering the composer.

## Tasks

### PR 1 — Android app and pairing

#### 1. Connection and remote client (`app/src/lib/api/`)
- `connection.ts`: `ServerConnection` (`server_url`, `device_id`, `token`), a `ConnectionStorage`
  interface (`load`, `save`, `clear`) with the Capacitor Preferences implementation on Android and a
  browser-storage one for the headless flows, and the client mode (`sidecar` | `remote`).
- `client.ts`: in remote mode, base URL from the stored connection and `Authorization: Bearer`;
  on `401` or missing config, drop the token and navigate to `/pair`. Desktop behavior unchanged.
- `pairDevice(serverUrl, code, deviceName)` calling `POST /api/auth/pair`; map invalid/expired,
  rate-limited, and unreachable errors to messages.

#### 2. `/pair` route (`app/src/routes/pair/+page.svelte`)
- The form from the implementation details, a pending state, error messages, and on success save
  the connection and go to `/`. Other routes redirect to `/pair` in remote mode without a
  connection.

#### 3. Capacitor project (`app/capacitor.config.ts`, `app/android/`)
- `@capacitor/core`, `@capacitor/android`, `@capacitor/preferences`, `@capacitor/app`, and
  `@capacitor/keyboard`; `webDir` is the static SPA build; `androidScheme: 'http'` so the page may
  call the server's plain-`http` Tailscale address.
- Client mode `remote` when `Capacitor.isNativePlatform()`; `app/src-tauri/`, desktop builds, and
  `make app` unchanged.
- Backend: server-mode CORS allows `http://localhost`, with a test.

#### 4. Android project and builds
- `npx cap add android` with the app id `local.verstehen.app`; `network_security_config.xml`
  for release (`100.64.0.0/10` only) and a debug variant adding `10.0.2.2`; Android auto-backup
  excludes the connection file.
- `make android-setup` (command-line SDK, build tools, JDK 21 for Capacitor 8, emulator, system
  image, and S24 and Tab S9
  virtual devices), `make android-debug` (debug `.apk`), `make android` (release `.apk`, signed
  with the user's key when present), and `make android-key` (decision 12).
- GitHub Actions: build and attach the signed `.apk` to tagged releases alongside the Arch package.

#### 5. Emulator verification for agents
- A documented loop in the verify skill: start a fake-model `--server` backend with a temporary data
  dir, mint a pairing code, install the debug `.apk`, open the emulator in the Device panel, pair,
  run a lesson turn, and capture screenshots and `adb logcat`; WebView DevTools over `adb` for
  inspecting the UI.

### PR 2 — Phone UI and recovery

#### 6. Layouts (`app/src/routes/(lesson)/+layout.svelte` and components)
- Width tiers per decision 11 with one shared source; check and fix the existing sidebar drawer.
- Phone top bar: menu button (drawer), session title, and right-panel tab buttons; tab content
  renders full screen; Lesson returns. Selection Ask and Ctrl+J switch to Side chat.
- Tablet: drawer sidebar, lesson and right panel side by side, the panel closable.
- Touch sizing under `pointer: coarse`; `env(safe-area-inset-*)` padding, `viewport-fit=cover` and
  `interactive-widget=resizes-content` in `app.html`, and the composer staying above the keyboard.
- Settings page: section nav becomes a list that opens a section full screen with a back control.

#### 7. `/graph` touch (`app/src/lib/graph/canvas.ts`, node card, context menu)
- For `pointerType === 'touch'`: no node drag; tap selects; long-press (with the click slop) calls
  `onContext`; d3-zoom handles one-finger pan and pinch; `touch-action: none` on the canvas.
- Node card and context menu stay inside the viewport.

#### 8. Phone Settings (`app/src/lib/components/settings*.svelte`)
- Section list per decision 5; `settings-connection.svelte` (address, device name, Disconnect);
  read-only Accounts variant; File access hidden in remote mode; Models edits the server's slots.

#### 9. Connection recovery (`app/src/lib/api/live.svelte.ts`)
- One helper owning online/visible state, a resume signal, and backoff (1s → 2s → 5s → 10s while
  visible; paused while hidden).
- `session-list.svelte`, `sync-badge.svelte`, `settings-sync.svelte`, and the graph, jobs, and side
  chat pages use it for `/api/events` and refetch on resume.
- `SessionController.attach()`: network failures wait for the resume signal and reattach instead
  of failing after two attempts; a finished turn appears from the refetch.
- "Reconnecting…" indicator component.

### Docs (each PR, for what it changes)
- `docs/decisions.md`: Capacitor instead of Tauri 2 Mobile; the phone connection file instead of
  the Keystore; the debug-only
  `10.0.2.2` cleartext; touch graph mapping; turn-stream reattach replacing the two-attempt limit;
  the "Reconnecting…" line.
- `docs/architecture/frontend-shell.md`, `api-and-events.md`, and `tooling.md`: remote mode,
  `/pair`, the Android build and emulator loop, layouts, recovery helper. `docs/feature-map.md`,
  `docs/status.md`, `docs/roadmap.md`.

## Verification

### PR 1
- **Vitest:** connection storage and mode selection; `401` → `/pair`; `/pair` errors.
- **Tests:** the guard allows only `localhost` and `100.64.0.0/10`, and adds only `10.0.2.2` in
  debug builds (JVM unit test and a Python config test), and blocks a real request on the emulator; desktop builds still bundle the sidecar; server CORS allows `http://localhost`.
- **Playwright** (`app/verify/shell/mobile-pair.flow.ts` at `360×780`): pair against a `--server`
  backend, bad code, `401` back to `/pair`.
- **Emulator (agent):** debug `.apk` on the S24 and Tab S9 virtual devices: pair, one fake-model
  lesson turn, screenshots attached to the PR.
- **Phone (user):** signed `.apk` on the S24 over Tailscale: pair, a live lesson turn, sync visible
  on the laptop.
- `make app` still builds; full `make check` and full `make verify` before the PR.

### PR 2
- **Vitest:** width tiers and `pointer: coarse` sizing; recovery helper backoff and resume;
  controller reattach after a simulated network drop; graph touch mapping (tap, long-press, drag
  pans); phone Settings sections.
- **Playwright at the S24 (`360×780`) and, for layout flows, the Tab S9 (`800×1280`, `1280×800`)**
  (`app/verify/shell/` unless noted):
  `mobile-lesson-turn` (drawer, a turn, composer above the keyboard area),
  `mobile-question-dock` (answer, dismiss, continue by touch),
  `mobile-right-panel` (Plan and Side chat full screen on the phone, side by side on the tablet,
  selection Ask), `mobile-graph` (`graph` area: tap card, long-press menu, drag pans without
  moving a node), `mobile-settings` (sections, Connection, Disconnect), and `mobile-reconnect`
  (offline during a turn → "Reconnecting…" → turn completes after going online).
- **Emulator (agent)** on both virtual devices for each part as it lands; **phone and tablet
  (user)** before the PR.
- Existing desktop flows stay green; each new flow gets a feature-map entry and checked screenshots
  attached to the PR.
- Before the PR into `dev`: full `make check`, full `make verify`, and `make verify-live`.
