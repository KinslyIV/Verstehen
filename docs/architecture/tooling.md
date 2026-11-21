# Tooling and packaging

Owns how the code is checked, verified, run, built, and released: the Makefile, the custom checks,
the fake model, the verify flows, the sidecar entry point and self-check, the Arch package, and CI.

## Where things run

| | Pixal (Ubuntu home server) | Laptop (Arch) |
|---|---|---|
| Role | agents write, test, verify, and build | runs the installed app; agents may use it through a T3 linked environment when Pixal is busy |
| Browser | Playwright's own Chromium for `make verify` and demo tests | an installed Chromium-family browser, or Playwright's downloaded on request |
| Real data | none | `~/.local/share/verstehen`: always set `VERSTEHEN_DATA_DIR` elsewhere |

## Code map

| Path | What it holds |
|---|---|
| `Makefile` | `setup`, `check` (= `check-backend` + `check-frontend`), `test`, `fmt`, `dev`, `verify`, `verify-run`, `verify-live`, `api-types`, `lock-migrations`, `app`, `app-image` |
| `tools/` | custom checks, each tested in `tools/tests/`: `check_comments.py` (≤ 3 lines per comment block), `check_migrations.py` (migration lock), `check_versions.py` (the three app versions agree), `check_feature_map.py` (every verify flow is in the feature map), `api_types.py` (generated types are fresh), `verify_build.py` (the SPA build guard), `dev.py` (`make dev`) |
| `ruff.toml`, `*/ruff.toml`, `pyrefly.toml`, `backend/pyproject.toml` | lint, banned APIs per package, types, import-linter layers, pytest (xdist `-n auto` from the Makefile) |
| `app/eslint.config.*`, Prettier, Vitest | frontend lint with boundaries, format, unit and browser-mode component tests |
| `backend/src/verstehen/cli.py`, `config.py` | the sidecar entry point (`serve`, logging, the port handshake) and environment settings |
| `backend/src/verstehen/self_check.py` | `verstehen --self-check`: resvg, PDFium, Pillow, `regex`, the prompts, Playwright and an offline headless page, the Claude CLI |
| `backend/src/verstehen/providers/fake.py`, `app/verify/scripts/*.json` | the scripted fake model and its reply scripts |
| `app/verify/*.flow.ts`, `fixtures.ts`, helpers | fake-model Playwright flows; `playwright.config.ts` |
| `app/verify-live/`, `playwright.live.config.ts` | the one real-model flow (Claude Code Haiku) |
| `packaging/` | `Dockerfile` (the prepared `verstehen-build` Arch image), `build.sh`, `container.sh`, `compile.sh`, `PKGBUILD`, `smoke.py`, the desktop entry |
| `.github/workflows/ci.yml`, `release.yml` | CI on PRs and pushes to `main`; releases on a `vX.Y.Z` tag |
| `.claude/skills/verify/SKILL.md` (also `.agents/skills/verify`) | the verify skill: how to run flows and what evidence to keep |

## How it works

- **Checks are code rules, not prose.** Every custom check's message says what to do instead.
  Corrections that a tool could catch become checks.
- **The fake model.** `VERSTEHEN_FAKE_MODEL_SCRIPT` enables only the fake account: `fake` streams
  scripted replies (text, thinking, tool calls, errors, delays, usage), `fake-title` serves titles
  and role-tagged worker replies.
- **Verify flows.** Each flow gets its own sidecar, Vite preview of the built SPA, and temporary
  data directory; the fixture saves a final `screenshot.png` and an always-on trace in
  `app/verify-output/` (some flows also save intermediate screenshots), and fails on console
  errors, page errors, and failed requests, except expected HTTP errors and requests a reload
  aborts.
  `make verify-run` reuses an unchanged SPA build behind the build guard.
- **Live verification.** `make verify-live` runs `lesson-first-turn` with the logged-in Claude Code
  on Haiku at low thinking; evidence in `app/verify-live-output/`. It never runs in CI.
- **Packaging.** `make app` builds the PyInstaller onedir sidecar and the Tauri shell inside the
  prepared Arch image (Docker volumes cache Cargo, npm, and uv), runs the frozen self-check and
  smoke tests (handshake, token refusal, migrations, shutdown), and writes
  `dist/verstehen-<version>-1-x86_64.pkg.tar.zst`. Neither Chromium nor the Claude Code CLI is
  bundled. `make app-image` refreshes the image.
- **CI** (`ci.yml`) runs `make setup`, `make check`, and `make verify` on GitHub-hosted Ubuntu and
  uploads `app/verify-output` on failure. Flows never retry, in CI or locally.
- **Releases** (`release.yml`): bump the versions in `backend/pyproject.toml`,
  `app/src-tauri/Cargo.toml`, and `app/src-tauri/tauri.conf.json`, merge, then push `vX.Y.Z`; the
  workflow checks the versions, runs `make app`, and publishes a GitHub Release.

## Traps found in M1–M9

- **Load-sensitive timing tests.** The thinking timer, the brief Stop-button state, the layout
  width test, the handoff and job-recovery flows have all failed under parallel load and passed on
  rerun. Under the flake rule ([workflow](../workflow.md)) these are bugs to fix, not reruns.
- **Parallel validation overloads Pixal.** Run heavy checks for one task at a time.
- **ESLint and Prettier caches** live in `app/node_modules/.cache`; a type change can hide a
  type-aware lint error in an unchanged file. CI runs the same command in a fresh workspace, so it
  starts with no cache; delete
  `app/node_modules/.cache/eslint` to force a full lint.
- **Long fixture histories** exceed the argument size limit; the verify fixture's `appendEntries`
  passes them through a temporary file.
