---
name: verify
description: Run Verstehen UI verification when changing anything the learner sees or when asked to verify the UI. Inspect and attach screenshots from the scripted Playwright flows.
---

Run from the repository root after `make setup`:

- `make verify` builds the static SPA and runs all flows in headless Playwright Chromium (`channel: 'chromium'`, also used by Vitest browser mode).
- `make verify FLOW=app-reaches-sidecar` builds and runs a single flow.
- Batch affected flows in one invocation: `make verify FLOW='layout-lesson-dark settings-appearance-light'`.
- `make verify-run FLOW='layout-lesson-dark settings-appearance-light'` reruns selected flows without rebuilding, only if the build guard passes. Omit `FLOW` to rerun all flows.
- Screenshots and always-on traces land in `app/verify-output/<flow>/` (Playwright may append a project or retry suffix).
- Open a trace with `cd app && npx playwright show-trace verify-output/<flow>/trace.zip`.
- `make verify-live` builds the SPA and runs `app/verify-live/lesson-first-turn.flow.ts` with the installed, logged-in Claude Code. It configures Haiku at low thinking via the settings API and uses the Claude subscription.
- Live artifacts are in `app/verify-live-output/<flow>/` with the same screenshot and trace settings.

When to run what:

- **While editing:** the affected `make check-backend` / `make check-frontend`, and the affected
  fake-model flows batched in one `make verify FLOW='…'` (or `make verify-run` after an unchanged
  build).
- **Before every commit:** full `make check`.
- **Once per milestone, at its end, before the milestone's PR into `dev`:** full `make verify` and
  `make verify-live`. Not per task, not per merge into `dev`.
- **On `dev` → `main`:** CI runs `make check` and `make verify`.
- **Docs-only and offline tooling work:** `make check`; no UI flows (CI still runs `make verify`).
- **Packaging changes:** `make app`; other changes don't need it.

The rerun guard requires a successful build from `make verify` or `make verify-live`, unchanged
frontend `src/` and `static/` paths/content, package and installed npm lockfiles, Node version, and frontend configuration
(`vite.config.*`, `svelte.config.*`, `tsconfig*.json`, `postcss.config.*`, `tailwind.config.*`,
`.node-version`, `.nvmrc`). It hashes `PUBLIC_*`, `VITE_*`, and `NODE_ENV` values without storing
their values, and verifies all build output. Failed builds invalidate the stamp; inputs changed
during a build cannot receive a valid stamp. Backend and flow-script edits can reuse the SPA.

Production dotenv files (`.env`, `.env.local`, `.env.production`, `.env.production.local`) disable
rerun reuse: their existence is checked, their contents are never read by the guard. `make verify`
still rebuilds and runs normally. `.env.example` and `.env.test` do not affect production builds.
Symlinked frontend inputs, configuration, or build output also disable reuse; full builds still work.
The guard covers this repository's default production build, not arbitrary build customization.
Custom config imports, a different `envDir`, additional environment dependencies, or manual
dependency edits require full `make verify` or extending the guard's explicit inputs.

Review may reuse passing results only when relevant source, configuration, dependencies, and
environment remain unchanged and no new issue has appeared. Record the command, revision or dirty
state, selected flows, and screenshot/trace paths. Rerun after meaningful edits, a failure, or a
new concern. A passing build guard permits build reuse; it does not validate earlier test results.

To add a flow, copy `app/verify/app-reaches-sidecar.flow.ts`, declare its JSON fake-model script
with `test.use({ script: 'verify/scripts/your-script.json' })`, and add the feature-map entry.
Static layout flows reuse `verify/scripts/health.json` without making model calls.
The shared fixture gives every flow its own sidecar, preview, and temporary data directory,
saves a full-page `screenshot.png` of the final page (a flow may save extra intermediate
screenshots when a state matters), and fails on console errors, uncaught page errors, and failed
requests, except expected HTTP errors and requests a reload aborts.
The live flow uses that fixture with `test.use({ script: 'none' })`. Assert streamed turn states
and learner controls because provider wording varies.

A flow that fails and then passes on rerun is a flake, and a flake is a bug: record it in
`docs/roadmap.md` (Known gaps) and fix it before merge. Never weaken an assertion or timeout to pass.
Every flow file must appear in a Verify flow column of `docs/feature-map.md` (`make check` enforces it).

New flows run in the default (dark) theme; only appearance and layout flows test a specific theme.
Playwright uses 1 worker on machines with 4 or fewer CPU threads and its default elsewhere and in CI.
Put cheap state permutations (such as the Settings account and tool states) in Vitest, with one
browser flow for the end-to-end case.

Look at the screenshots yourself and attach the ones you checked to the PR.
Keep logic permutations in cheap offline tests and representative real flows in this suite.
Focused iteration plus full integration verification preserves coverage as the app grows.
