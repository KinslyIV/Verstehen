# Frontend shell

Owns the app around the lesson: routes and the lesson layout (sidebar, header, right panel), the
settings page, the markdown renderer, the shadcn-svelte components, theming, the Tauri shell, and the
Android app (Capacitor) with its remote mode and `/pair`.
Feature UI lives with its area (questions in [teaching](teaching.md), cards in [jobs](jobs.md), …).

LearnHarness spec: behavior from LH, look from T3 Code ([overview](../learnharness/overview.md)).

## Code map

`app/`:

| Path | What it holds |
|---|---|
| `src/app.html`, `src/routes/+layout.svelte` | the page shell (declares the favicon); the root layout holds CSS and theme only |
| `src/routes/(lesson)/+layout.svelte` | the lesson shell: sidebar (`+ Teaching` and `Practice` buttons, the `Teaching | Practice | All` filter, session list, and optional live sync badge from `sync-badge.svelte`), header, and the resizable right panel with the tabs Plan, Jobs, Activity (placeholder until M11), and Side chat |
| `src/routes/(lesson)/+page.svelte`, `session/new/`, `session/[id]/`, `graph/` | the new-session screen (`/` and `/session/new`), a lesson, the knowledge graph |
| `src/routes/settings/+page.svelte`, `lib/components/settings*.svelte` | settings outside the lesson group: Appearance, Models, Accounts, Lesson, Graph, Tools, Sync (`?section=sync` deep-links; the section derives from reactive `page.url` and clicks update the URL). `settings-sync.svelte` keeps one in-memory attempt (install or OAuth) through TOFU and SSH-password prompts, loads the three server cards independently with per-card errors, and discards stale responses (cards by a generation counter, status and install-status requests each by their own sequence number) after disconnect or a server change; it shows a warning when the server cannot identify this laptop |
| `src/routes/pair/+page.svelte` | the pairing form (outside the lesson group): server address, code, device name |
| `src/lib/api/connection.ts` | `ServerConnection`, the storage behind it (Capacitor Preferences on Android, `localStorage` for headless flows), the client mode, and server-address rules |
| `src/routes/lesson-test-harness.svelte`, `session-thread-test-page.svelte` | wrappers for component tests |
| `src/lib/markdown/` | assistant markdown: Streamdown-style top-level blocks, each parsed by LH's unified/remark stack and sanitized; math, Shiki code, app-owned Mermaid; learner text stays plain |
| `src/lib/components/ui/` | shadcn-svelte components, generated with its CLI (excluded from the comment check) |
| `src/lib/components/reasoning.svelte` | the thinking row |
| `src-tauri/` | the Rust shell (`lib.rs`), `tauri.conf.json` (window, CSP, shell allow-list), icons |
| `capacitor.config.ts`, `android/` | the Capacitor Android project around the static build (`webDir: build`, `androidScheme: 'http'`, app id `local.verstehen.app`): manifest, backup rules, and `CleartextGuard` / `GuardedWebViewClient` in `android/app/src/main/java/local/verstehen/app/`; generated parts (copied web assets, builds) are git-ignored |

## How it works

- **Sync settings:** Disconnect invalidates in-flight install polls. A terminal `oauth_cancelled`
  response ends browser sign-in and re-enables account actions; transient poll errors still retry.
- **SvelteKit SPA** with `adapter-static`; no server rendering. Svelte 5 runes only; shared state in
  `.svelte.ts` modules; `$effect` only for real side effects.
- **Look:** sleek and minimal, modeled on T3 Code. Tailwind v4, shadcn-svelte on bits-ui,
  tailwind-variants, `@lucide/svelte`. Dark by default; Dark / Light / System through mode-watcher,
  saved in localStorage and applied before first paint.
- **New sessions:** `/session/new` is the teaching screen and `/session/new?mode=practice` the
  practice one; the `Teach | Practice` toggle navigates between them without remounting, so the
  draft and the picked nodes stay. The kind filter is remembered in `localStorage`.
- **Sidebar refresh:** session notifications update the list and its pending practice indicators.
  Sync-status notifications refresh the badge and Settings → Sync.
- **Layout state:** the sidebar collapses with Ctrl+B and remembers its state; the right panel
  starts closed; toggling it remembers its visibility, and it remembers its width (default 25%,
  20–40%). Opening it from code (a new plan, a plan block, Ctrl+J) changes only the live state.
  The right panel is hidden on `/graph`.
- **Markdown streaming:** finished blocks keep their parse and DOM while the tail changes, so long
  replies stay responsive.
- **Tauri shell:** starts the sidecar with a fresh token, waits for the port line and a 200 health
  response (30 s, then a native error dialog naming the log), and exposes only
  `sidecar_connection`. The shell plugin opens exactly the ChatGPT sign-in URLs and the Claude
  Code setup page in the system browser. The CSP is relaxed for demos and allows `blob:` images.

## Remote mode and the Android app

- **Two client modes** (`clientMode()` in `connection.ts`): `sidecar` (desktop and `make dev`) and
  `remote`. Remote is chosen when `Capacitor.isNativePlatform()` is true (the Android app, always)
  or the build sets `PUBLIC_VERSTEHEN_CLIENT` to `remote` (headless flows) or `android` (the app's
  build); normal builds never do.
  `app/src-tauri/` is untouched; the desktop still bundles and starts the sidecar.
- **Requests in remote mode** go to the stored `server_url` with `Authorization: Bearer <token>`,
  using the WebView's own `fetch` so SSE streams (Capacitor's native HTTP plugin cannot stream and
  is not used, and `plugins.CapacitorHttp.enabled` is `false`). Every remote request and the pairing
  request use `redirect: 'error'`, so an allowed server cannot send the app to another address. A
  missing connection or a `401` drops the token that request used (only if a newer pairing has not
  replaced it; writes to the connection are serialized), keeps the server address, and navigates
  to `/pair`; the root `+layout.ts` also redirects every other route there when no
  connection is stored.
- **`/pair`** takes the server's Tailscale address (`100.x.y.z:port`, `http://` implied; anything
  outside `100.64.0.0/10`, or typed in any non-canonical form (hex, octal, short, `1.2.3.4e0`), is
  refused, plus the hosts in `PUBLIC_VERSTEHEN_EXTRA_HOSTS`, which only
  the debug `.apk` and the headless flows set), the 8-character code (any case), and a device name
  (default "Phone"), then calls `POST /api/auth/pair`, saves the connection, and opens `/`. Wrong
  or expired codes, rate limiting, and an unreachable server each show their own message.
- **The connection** (`server_url`, `device_id`, `token`) lives in Capacitor Preferences, the app's
  private `CapacitorStorage` file, which the backup rules exclude (not the Keystore: a rooted phone
  or backup tool could read it, and revoking the device on the laptop is the remedy).
- **Cleartext is Tailscale-only, enforced natively.** The page is served from `http://localhost`
  (`androidScheme: 'http'`) so it can call the server's plain-`http` address. Android's network
  security config cannot express a CIDR range, so it allows cleartext and `GuardedWebViewClient`
  blocks every `http://` request except `localhost`, `100.64.0.0/10`, and `10.0.2.2` in debug
  builds; `https` is untouched. The guard only blocks: allowed requests are made by the WebView
  itself, so POST bodies and SSE are unchanged.

## Traps found in M1–M9

- **Early desktop requests must wait for the sidecar connection.** Accounts once opened before the
  connection existed; requests now wait, and failed lookups are cleared for retry.
- **Vite's Host rewrite** broke the backend's same-origin check for browser writes until the proxy
  was fixed.
- **mode-watcher 1.1.0 persists "system" at import,** so the app writes the stored preference
  before the library initializes.
- **One huge paragraph still re-parses as one block** (as in LH). Smooth streaming of very long
  single paragraphs is not established; see the [roadmap](../roadmap.md).
- **The Tauri window is checked by hand** on the laptop; agents never run it.
