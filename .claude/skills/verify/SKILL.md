---
name: verify
description: Run Verstehen UI verification when changing anything the learner sees or when asked to verify the UI. Inspect and attach screenshots from the scripted Playwright flows.
---

Run from the repository root after `make setup`:

- `make verify` builds the static SPA and runs all flows in headless Playwright Chromium.
- `make verify FLOW=app-reaches-sidecar` builds and runs a single flow.
- Screenshots and always-on traces land in `app/verify-output/<flow>/` (Playwright may append a project or retry suffix).
- Open a trace with `cd app && npx playwright show-trace verify-output/<flow>/trace.zip`.

To add a flow, copy `app/verify/app-reaches-sidecar.flow.ts`, declare its JSON fake-model script
with `test.use({ script: 'verify/scripts/your-script.json' })`, and add the feature-map entry.
The shared fixture gives every flow its own sidecar, preview, and temporary data directory,
and fails on console errors, uncaught page errors, and failed requests.

Look at the screenshots yourself and attach the ones you checked to your report.
