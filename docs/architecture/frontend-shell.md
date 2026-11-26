# Frontend shell

Owns the app around the lesson: routes and the lesson layout (sidebar, header, right panel), the
settings page, the markdown renderer, the shadcn-svelte components, theming, what the page expects of the Qt shell, and the
Android app (Capacitor) with its remote mode and `/pair`.
Feature UI lives with its area (questions in [teaching](teaching.md), cards in [jobs](jobs.md), …).

LearnHarness spec: behavior from LH, look from T3 Code ([overview](../learnharness/overview.md)).

## Code map

`app/`:

| Path | What it holds |
|---|---|
| `src/app.html`, `src/routes/+layout.svelte` | the page shell, theme, and initial saved model catalog. In remote mode the catalog starts after pairing and is reset on return to the pairing screen. |
| `src/routes/(lesson)/+layout.svelte` | the lesson shell: sidebar (`+ Teaching`, `Practice`, and `Chat` buttons, the `Teaching | Practice | Chat | All` filter, session list, and optional live sync badge from `sync-badge.svelte`), header, and the resizable right panel with the tabs Plan, Jobs, Activity (placeholder until M11), and Side chat; below 768 px a phone top bar, the right-panel tab screen, and the "Reconnecting…" line (see Layouts and touch) |
| `src/lib/components/session-list.svelte`, `sidebar-folder-row.svelte`, `new-folder-row.svelte`, `lib/graph/source-directory.svelte.ts`, `source-drop.svelte.ts` | the sidebar folder tree: rows, folder menu, drag and drop, and the shared directory reader |
| `src/routes/(lesson)/+page.svelte`, `session/new/`, `session/[id]/`, `graph/` | the new-session screen (`/` and `/session/new`), a lesson, the knowledge graph |
| `src/routes/settings/+page.svelte`, `lib/components/settings*.svelte` | settings outside the lesson group: Appearance, Models, Accounts, Lesson, Prompts, Graph, Tools, and Sync on the desktop or Connection in remote mode (`?section=sync` deep-links; the section derives from reactive `page.url` and clicks update the URL). `settings-sync.svelte` keeps one in-memory attempt (install or OAuth) through TOFU and SSH-password prompts, loads the three server cards independently with per-card errors, and discards stale responses (cards by a generation counter, status and install-status requests each by their own sequence number) after disconnect or a server change; it shows a warning when the server cannot identify this laptop |
| `src/routes/pair/+page.svelte` | the pairing form (outside the lesson group): server address, code, device name |
| `src/lib/api/connection.ts` | `ServerConnection`, the storage behind it (Capacitor Preferences on Android, `localStorage` for headless flows), the client mode, and server-address rules |
| `src/routes/settings/+page.svelte`, `lib/components/settings*.svelte` | settings outside the lesson group: Appearance, Models, Accounts, Lesson, Prompts, Graph, Tools, Sync (`?section=sync` deep-links; Prompts is owned by [teaching](teaching.md); the section derives from reactive `page.url` and clicks update the URL). `settings-sync.svelte` keeps one in-memory attempt (install or OAuth) through TOFU and SSH-password prompts, loads the three server cards independently with per-card errors, and discards stale responses (cards by a generation counter, status and install-status requests each by their own sequence number) after disconnect or a server change; it shows a warning when the server cannot identify this laptop |
| `src/routes/lesson-test-harness.svelte`, `session-thread-test-page.svelte` | wrappers for component tests |
| `src/lib/markdown/` | assistant markdown: Streamdown-style top-level blocks, each parsed by LH's unified/remark stack and sanitized; math, Shiki code, app-owned Mermaid; learner text stays plain |
| `src/lib/components/ui/` | shadcn-svelte components, generated with its CLI (excluded from the comment check) |
| `src/lib/components/reasoning.svelte` | the thinking row |
| `src/lib/api/client.ts` (`openExternal`, `onLinkRefused`) | opening an external link with `window.open`, and the `verstehen:link-refused` window event the desktop shell raises when it declines one |
| `backend/src/verstehen/desktop/` | the Qt shell that hosts this page on the desktop: window, starting and failure pages, link rules, downloads, DevTools ([architecture](../architecture.md)) |
| `capacitor.config.ts`, `android/` | the Capacitor Android project around the static build (`webDir: build`, `androidScheme: 'http'`, app id `local.verstehen.app`): manifest, backup rules, and `CleartextGuard` / `GuardedWebViewClient` in `android/app/src/main/java/local/verstehen/app/`; generated parts (copied web assets, builds) are git-ignored |

## How it works

- **Sync settings:** Disconnect invalidates in-flight install polls. A terminal `oauth_cancelled`
  response ends browser sign-in and re-enables account actions; transient poll errors still retry.
- **SvelteKit SPA** with `adapter-static`; no server rendering. Svelte 5 runes only; shared state in
  `.svelte.ts` modules; `$effect` only for real side effects.
- **Look:** sleek and minimal, modeled on T3 Code. Tailwind v4, shadcn-svelte on bits-ui,
  tailwind-variants, `@lucide/svelte`. Dark by default; Dark / Light / System through mode-watcher,
  saved in localStorage and applied before first paint.
- **New sessions:** `/session/new` is the teaching screen, `/session/new?mode=practice` the
  practice one, and `/session/new?mode=chat` the general chat one; the `Teach | Practice | Chat`
  toggle navigates between them without remounting, so the draft and picked nodes stay (`NodePicker`
  hides in `chat` mode). The 4-way kind filter is remembered in `localStorage`.
- **Sidebar refresh:** session notifications update the list and its pending practice indicators.
  Sync-status notifications refresh the badge and Settings → Sync.
- **Sidebar folders:** `session-list.svelte` draws `flattenSessionTree(buildSessionTree(...))`
  (`graph/source-organization.ts`) over the shared source organization, read by
  `SourceDirectoryReader` (`graph/source-directory.svelte.ts`) on mount and on `graph-changed` and
  `sessions-changed` window events (the notification bridge also fires both after a reconnect).
  Writes are queued operations (`/api/graph/sources`) that each end in a fresh read, never the POST
  snapshot; a failed read keeps the last directory, and with none the list is flat and offers no
  folder controls. Folder rows (`sidebar-folder-row.svelte`) only open or close on click; the open
  set is saved in `localStorage` (`verstehen-sidebar-open-folders`). Right-click or long-press opens
  Rename, New subfolder, New teaching here, New practice here, New chat here, and Delete, which is enabled only when `folderHoldsNoSources` and then
  sends `delete-folder-tree` for that folder; the server recomputes the subtree in its transaction
  and removes all of it or answers 409. Drag payload and drop
  rules are Chains' (`SourceDrop`, shared with the chains table); `layout.coarse` turns `draggable`
  off on touch-primary layouts and `SourceDragRow` cancels touch-origin drags on hybrid devices.
- **Session menu and folder starts:** a session's context menu has **Move to folder** (a submenu of
  `folderChoices`: No folder, then the tree indented; the current parent is disabled), which sends
  the same `move` operation as a drop, so touch can move sessions too. **New teaching here** and
  **New practice here** open `/session/new?folder=<id>` (`newSessionQuery`); `new-session.svelte`
  sends it as `folder_id` on `POST /api/sessions` ([session](session.md#how-it-works)).
- **Transcript width:** Settings → Appearance → **Transcript width** is a slider from 46 to 120 rem
  in 2 rem steps, with **Full** (no cap) as the default. `TranscriptWidth`
  (`layout/transcript-width.svelte.ts`) keeps it per device in `localStorage`
  (`verstehen-transcript-width`) and sets `--verstehen-transcript-max` on `<html>`; a script in
  `app.html` sets it before first paint. The lesson thread's header and transcript cap their column
  with it (`layout.css`); as in LearnHarness, the composer, question and practice docks, stats bar,
  and new-session screen keep their fixed `max-w-3xl`. A missing or invalid stored value means Full.
- **Scroll to bottom:** the thread's `<Scroller.Button>` is always mounted (also while a turn or a
  question is pending) and shows only while scrolled away from the end; the turn minimap rail is
  documented in [session](session.md#turn-minimap).
- **Floating bottom block:** as in LearnHarness, the error line, the composer or the question and
  practice dock (and their folded bars), and the stats bar sit in one overlay over the bottom of the
  transcript (`session-thread.svelte`), with a short gradient above it. The overlay's height
  (`bind:clientHeight`) becomes the transcript's bottom padding (`--dock-reserve`); while one
  question or problem owns the dock the reserve only grows, so folding and unfolding (still at 96 and
  16 px from the end) are visual only and never change the scroll area's height. The scroll-to-bottom
  button follows the live overlay height. A wheel over the overlay scrolls the transcript unless
  something inside it can scroll (`session/dock-wheel.ts`).
- **Stats bar:** `stats-bar.svelte` sits under the composer or dock on `/session/{id}` once stats
  load (`41k / 200k · CLI`, `? · —` before a completed reply, absent on `/` or `/session/new`):
  `—` for an unpriced model, never a dollar zero. Its popover is Session stats (see [session](session.md#session-stats)); outside
  press or Esc closes it. On touch the button is 44 px tall and the popover stays inside the screen.
- **Sidebar search:** the field above the kind filter (also on the phone drawer) scores titles with
  `fuzzyScore` through `buildSessionTree`: the kind filter narrows first, folders lead, each level
  ranks by score with activity breaking ties, and folders without matches hide. While a query is
  set every folder shows open; a folder closed then is remembered only for that exact query
  (`SearchFolds` in `session-list-model.ts`), never in the saved open set. The field owns the
  walk: Up and Down cycle the visible session rows (wrapping, highlighted, scrolled into view),
  Enter opens the walked row or the first match, and Enter or Esc blurs the field and keeps the
  query. A query change or a click on a row clears the walk. Ctrl or Cmd+Shift+F opens a
  collapsed sidebar or the closed drawer and focuses the field once it mounts (the listener is
  `search-shortcut.svelte` in the lesson layout), unless a dialog, popover, or menu is open; a new
  subfolder made during a search changes only the search state, never the saved open set.
- **Layout state:** the sidebar collapses with Ctrl+B and remembers its state; the right panel
  starts closed; toggling it remembers its visibility, and it remembers its width (default 25%,
  20–40%). Opening it from code (a new plan, a plan block, Ctrl+J) changes only the live state.
  The right panel is hidden on `/graph`.
- **Markdown streaming:** finished blocks keep their parse and DOM while the tail changes, so long
  replies stay responsive.
- **Qt shell:** the page is a same-origin SPA that FastAPI serves in desktop mode, so the client
  uses relative URLs with no connection lookup, no token header, and no CORS. The shell
  (`desktop/shell.py`) owns the first and last screens: the window is visible at once with a quiet
  "Starting Verstehen…" page, and a start that fails or takes over 30 s shows a "couldn't start"
  page with the reason and the log path (`desktop/pages.py`). The app loads only after the server
  is healthy and the token is set as an HttpOnly, SameSite=Strict cookie in the window's cookie
  store, so the page never sees the token. The app's CSP is sent by FastAPI
  ([API and events](api-and-events.md#access)). The persistent web profile lives under
  `<data dir>/webengine` and `webengine-cache`.
- **Links and windows:** the window stays on the app's origin. `acceptNavigationRequest` and
  `newWindowRequested` open exactly the ChatGPT sign-in URLs (`auth.openai.com`) and the Claude
  Code setup page in the system browser (`desktop/links.py`); every other navigation is refused.
  The client opens links with `window.open`, which cannot report a refusal, so the shell runs a
  script that dispatches `verstehen:link-refused` with the URL; Settings → Tools listens and
  shows "Verstehen can't open <url>. Open it in your browser." Files dropped on the window do not
  navigate. A download opens a save dialog starting in the Downloads folder; cancelling cancels
  the download.
- **DevTools and icon:** DevTools exist only when the app starts with `VERSTEHEN_DEVTOOLS=1`; F12
  opens them in their own window, which closes with the app. The window icon comes from the
  package icons (`VERSTEHEN_ICONS_DIR`, else `packaging/icons`).
- **Off-screen rows:** each transcript row is a `content-visibility: auto` placeholder
  (`message-scroller-item.svelte`, intrinsic size 10 rem) so a long lesson mounts fast; LearnHarness
  renders every row ([decisions](../decisions.md)). Chromium anchors the scroll position as
  placeholders take their real height.
- **Settings → Tools on the desktop:** the Demo browser section is hidden when `/api/health` says
  `desktop: true`, because the desktop checks demos in its own engine ([jobs](jobs.md)).
- **Settings → Models:** the slot pickers, then a refresh button with a status line (updated, which
  accounts could not be reached, or the request failure); see [providers](providers.md).

## Remote mode and the Android app

- **Two client modes** (`clientMode()` in `connection.ts`): `sidecar` (the desktop and `make dev`:
  requests go to the page's own origin) and `remote`. Remote is chosen when `Capacitor.isNativePlatform()` is true (the Android app, always)
  or the build sets `PUBLIC_VERSTEHEN_CLIENT` to `remote` (headless flows) or `android` (the app's
  build); normal builds never do.
- **Requests in remote mode** go to the stored `server_url` with `Authorization: Bearer <token>`,
  using the WebView's own `fetch` so SSE streams (Capacitor's native HTTP plugin cannot stream and
  is not used, and `plugins.CapacitorHttp.enabled` is `false`). Every remote request and the pairing
  request use `redirect: 'error'`, so an allowed server cannot send the app to another address. A
  missing connection or a `401` drops the token that request used (only if a newer pairing has not
  replaced it; writes to the connection are serialized), keeps the server address, and navigates
  to `/pair`; the root `+layout.ts` also redirects every other route there when no
  connection is stored.
- **`/pair`** takes the server's Tailscale address (`100.x.y.z:port`, `http://` implied; anything
  outside `100.64.0.0/10`, or typed in any non-canonical form (hex, octal, short, `1.2.3.4e0`) or with `user@`, is
  refused, plus the hosts in `PUBLIC_VERSTEHEN_EXTRA_HOSTS`, which only
  the debug `.apk` and the headless flows set), the 8-character code (any case), and a device name
  (default "Phone", or "Tablet" when the shorter screen side is at least 600 px), then calls `POST /api/auth/pair`, saves the connection, and opens `/`. Wrong
  or expired codes, rate limiting, and an unreachable server each show their own message.
- **The connection** (`server_url`, `device_id`, `token`) lives in Capacitor Preferences, the app's
  private `CapacitorStorage` file, which the backup rules exclude (not the Keystore: a rooted phone
  or backup tool could read it, and revoking the device on the laptop is the remedy). It is one
  JSON value, so a re-pair that is interrupted never leaves a new address beside an old token; a
  record that is not an address alone or all three fields (including per-field keys) loads as no
  connection and is deleted.
- **Cleartext is Tailscale-only, enforced natively.** The page is served from `http://localhost`
  (`androidScheme: 'http'`) so it can call the server's plain-`http` address. Android's network
  security config cannot express a CIDR range, so it allows cleartext and `GuardedWebViewClient`
  blocks every `http://` request except `localhost`, `100.64.0.0/10`, and `10.0.2.2` in debug
  builds; `https` is untouched. The guard only blocks: allowed requests are made by the WebView
  itself, so POST bodies and SSE are unchanged.

## Layouts and touch

- **Width tiers** (`layout.tier` in `lib/layout/tiers.svelte.ts`): phone below 768 px, tablet
  768–1279 px, desktop from 1280 px. Tailwind's `max-md:` and `md:` carry the phone styling; the
  tablet and desktop split is the sidebar (a drawer below 1280 px, inline above) and the panel.
- **Phone:** a top bar (drawer button, session heading, then the four right-panel buttons). A panel
  button opens that tab full screen over the inert lesson and the bar shows a "Lesson" back
  button; a new plan does not switch screens. The drawer closes on navigation (`DrawerCloser`), and
  navigating to another lesson or the new-session screen returns to the lesson screen.
- **Tablet:** the drawer plus the right panel beside the lesson, closable; the width is
  remembered. **Desktop** is unchanged.
- **Touch** (`pointer: coarse`, a custom Tailwind `coarse:` variant): buttons and icon buttons get
  44 px targets. `/graph` takes a tap to open the card, a 500 ms press for the menu, any drag past
  8 px to pan, and a pinch to zoom; touch never drags a node. Mouse input is as in LearnHarness.
  The node card is capped to the canvas height and scrolls inside.
- **Android Back:** `session/android-back.ts` keeps one native listener for every caller; the root
  layout registers it so every page is covered. It closes an open overlay first (the phone drawer,
  a dialog, a menu, or the graph's context menu) by pressing Escape; otherwise it offers Back to the
  lesson's `requestAbort`, the same function as Escape, so a pending question, an active problem, or
  a running turn opens its confirmation; otherwise Back goes back in history or leaves the app.
- **Phone Settings:** a section list; a section opens full screen and the back button returns to
  the list. Models edits the server's slots, Accounts is read-only, File access is hidden, and
  Connection (server address, device name, Disconnect) replaces Sync. Disconnect waits at most 5 s
  for the server to revoke the device, then forgets the token anyway.
- **Safe areas and the keyboard:** `viewport-fit=cover` and `interactive-widget=resizes-content`;
  `--safe-top` and `--safe-bottom` pad the bars and docks. The composer, docks, and the empty
  new-session screen shrink with the keyboard instead of overflowing.
- **Android system bars:** `SystemBars.setStyle` follows the theme, and a dark native window
  background keeps them from flashing white while the page loads.

## Stream recovery

`lib/api/live.svelte.ts` owns the foreground and network state. A stream that fails with a
network error waits 1, 2, 5, then 10 s (paused while the app is hidden, restarted at once on
`visibilitychange`, `pageshow`, or `online`) and reopens. `live.follow` keeps notification and
side-chat streams open, refetching after each reconnect. A lesson turn reattaches to its run and
replays the log; server errors still fail the turn. A side-chat answer does the same: its feed
waits and reattaches to `GET …/side-chats/{thread}/stream`, which replays the text so far, and stops on
`done`, `error`, or dispose. While a stream is down and the app is in front,
`ReconnectingLine` shows "Reconnecting…" at the top of the main column. The notification stream
lives in `NotificationBridge` in the lesson layout, because the phone drawer unmounts the sidebar.
The graph page reruns its first load on the next `graph-changed` event while it has failed, and a
later successful refresh clears its error. On the remote client the Settings sections that read
the server (`settings-reconnect.ts`) follow the same stream and load a failed read once the
connection returns; a section that already has its data is left alone, so edits are kept.

## Traps found in M1–M9

- **A hidden window hides a slow start.** The window used to stay hidden until the server was
  healthy, so a slow start looked like nothing happening. It is visible from the start now, with
  the shell's starting page.
- **Vite's Host rewrite** broke the backend's same-origin check for browser writes until the proxy
  was fixed.
- **mode-watcher 1.1.0 persists "system" at import,** so the app writes the stored preference
  before the library initializes.
- **One huge paragraph still re-parses as one block** (as in LH). Smooth streaming of very long
  single paragraphs is not established; see the [roadmap](../roadmap.md).
- **The Qt window is checked by hand** on the laptop; agents run it only offscreen in tests. Still
  to check there: trackpad pinch, file drag-and-drop, window flashing and the window icon on
  Wayland ([roadmap](../roadmap.md#known-gaps)).
