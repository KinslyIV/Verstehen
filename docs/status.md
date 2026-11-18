# Status

> Updated at the end of every piece of work. Last update: 2026-11-18.

## Where we are

**M1 task 1: environment, repository scaffolding, and checks implemented.**

- Python 3.14 uv project with empty feature packages and enforced dependency layers.
- SvelteKit SPA, TypeScript, Tailwind v4, neutral shadcn-svelte initialization; no real UI yet.
- `make setup`, `make check`, `make test`, `make fmt`, and `make lock-migrations`.
- Comment/docstring length and migration immutability checks, with offline pytest tests.
- Part A LearnHarness docs and Part B architecture, scope, and decisions remain the specification.

## Next

1. M1 sidecar + store + data dir + log.
2. `make verify` + fake model + verify skill. The user must first run
   `sudo npx playwright install-deps chromium` once on Pixal; agents install Playwright's Chromium.
3. Packaging proof with `make app` inside an Arch container, then laptop installation.
4. Empty UI layout (sidebar, lesson/composer, right panel, settings).
5. M2 session core, M3 real providers, M4 question tools, M5 teaching flow.

## Open questions

- M1 task 1 implementation choices are listed in its report for orchestrator review.
- Later providers remain in [architecture](architecture.md#open-questions).
