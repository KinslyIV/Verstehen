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

Use affected flows while editing UI work. Run full `make verify` before merging UI work and after
shared UI or runtime changes. Run the affected `make check-backend` / `make check-frontend` while
editing and full `make check` before every commit. Desktop packaging needs `make app` when
packaging changes; unrelated changes do not require it.

The rerun guard requires a successful `make verify` build, unchanged frontend `src/` and `static/`
paths/content, package and installed npm lockfiles, Node version, and frontend configuration
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
saves a full-page `screenshot.png` of the final page (flows take no screenshots themselves),
and fails on console errors, uncaught page errors, and failed requests.

Look at the screenshots yourself and attach the ones you checked to your report.
Keep logic permutations in cheap offline tests and representative real flows in this suite.
Focused iteration plus full integration verification preserves coverage as the app grows.
