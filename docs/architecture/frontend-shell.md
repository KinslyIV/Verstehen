# Frontend shell

Owns the app around the lesson: routes and the lesson layout (sidebar, header, right panel), the
settings page, the markdown renderer, the shadcn-svelte components, theming, and the Tauri shell.
Feature UI lives with its area (questions in [teaching](teaching.md), cards in [jobs](jobs.md), …).

LearnHarness spec: behavior from LH, look from T3 Code ([overview](../learnharness/overview.md)).

## Code map

`app/`:

| Path | What it holds |
|---|---|
| `src/app.html`, `src/routes/+layout.svelte` | the page shell (declares the favicon); the root layout holds CSS and theme only |
| `src/routes/(lesson)/+layout.svelte` | the lesson shell: sidebar (`+ Teaching` and `Practice` buttons, the `Teaching | Practice | All` filter and session list), header, and the resizable right panel with the tabs Plan, Jobs, Activity (placeholder until M11), and Side chat |
| `src/routes/(lesson)/+page.svelte`, `session/new/`, `session/[id]/`, `graph/` | the new-session screen (`/` and `/session/new`), a lesson, the knowledge graph |
| `src/routes/settings/+page.svelte`, `lib/components/settings*.svelte` | settings outside the lesson group: Appearance, Models, Accounts, Lesson, Graph, Tools |
| `src/routes/lesson-test-harness.svelte`, `session-thread-test-page.svelte` | wrappers for component tests |
| `src/lib/markdown/` | assistant markdown: Streamdown-style top-level blocks, each parsed by LH's unified/remark stack and sanitized; math, Shiki code, app-owned Mermaid; learner text stays plain |
| `src/lib/components/ui/` | shadcn-svelte components, generated with its CLI (excluded from the comment check) |
| `src/lib/components/reasoning.svelte` | the thinking row |
| `src-tauri/` | the Rust shell (`lib.rs`), `tauri.conf.json` (window, CSP, shell allow-list), icons |

## How it works

- **SvelteKit SPA** with `adapter-static`; no server rendering. Svelte 5 runes only; shared state in
  `.svelte.ts` modules; `$effect` only for real side effects.
- **Look:** sleek and minimal, modeled on T3 Code. Tailwind v4, shadcn-svelte on bits-ui,
  tailwind-variants, `@lucide/svelte`. Dark by default; Dark / Light / System through mode-watcher,
  saved in localStorage and applied before first paint.
- **New sessions:** `/session/new` is the teaching screen and `/session/new?mode=practice` the
  practice one; the `Teach | Practice` toggle navigates between them without remounting, so the
  draft and the picked nodes stay. The kind filter is remembered in `localStorage`.
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
