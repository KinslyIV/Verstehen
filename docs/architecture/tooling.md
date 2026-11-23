# Tooling and packaging

Owns how the code is checked, verified, run, built, and released: the Makefile, the custom checks,
the fake model, the verify flows, the sidecar entry point and self-check, the Arch package, the Android app build and its emulator loop, and CI.

## Where things run

| | Pixal (Ubuntu home server) | Laptop (Arch) |
|---|---|---|
| Role | agents write, test, verify, and build | runs the installed app; agents may use it through a T3 linked environment when Pixal is busy |
| Browser | Playwright's own Chromium for `make verify` and demo tests | an installed Chromium-family browser, or Playwright's downloaded on request |
| Real data | none | `~/.local/share/verstehen`: always set `VERSTEHEN_DATA_DIR` elsewhere |

## Code map

| Path | What it holds |
|---|---|
| `Makefile` | `setup`, `check` (= `check-backend` + `check-frontend`), `test`, `fmt`, `dev`, `verify`, `verify-run`, `verify-live`, `api-types`, `lock-migrations`, `app`, `app-image`, `android-setup`, `android-debug`, `android`, `android-key` (`AREA='...'` scopes test and flow targets to the 9 architecture areas; `SLOW=1` includes `@pytest.mark.slow` in area-scoped pytest runs) |
| `tools/` | custom checks and runners, each tested in `tools/tests/`: `check_comments.py` (≤ 3 lines per comment block), `check_migrations.py` (migration lock), `check_versions.py` (the three app versions agree), `check_feature_map.py` (every verify flow is in the feature map), `test_areas.py` (enforces 9-area organization across `backend/tests/<area>/`, frontend Vitest globs, and `app/verify/<area>/`, and routes `pytest`, `vitest`, and `verify`), `api_types.py` (generated types are fresh), `verify_build.py` (the SPA build guard), `dev.py` (`make dev`) |
| `ruff.toml`, `*/ruff.toml`, `pyrefly.toml`, `backend/pyproject.toml` | lint, banned APIs per package, types, import-linter layers, pytest (`live` and `slow` markers; xdist `-n auto` via `tools/test_areas.py`) |
| `app/eslint.config.*`, Prettier, Vitest | frontend lint with boundaries, format, unit and browser-mode component tests |
| `backend/src/verstehen/cli.py`, `config.py` | the sidecar entry point (`serve`, logging, the port handshake), the `import-learnharness` subcommand, and environment settings |
| `backend/src/verstehen/self_check.py` | `verstehen --self-check`: resvg, PDFium, Pillow, `regex`, the prompts, Playwright and an offline headless page, the Claude CLI |
| `backend/src/verstehen/providers/fake.py`, `app/verify/scripts/*.json` | the scripted fake model and its reply scripts |
| `app/verify/<area>/*.flow.ts`, `fixtures.ts`, helpers | fake-model Playwright flows grouped by the 9 architecture areas; `playwright.config.ts` |
| `app/verify-live/`, `playwright.live.config.ts` | the one real-model flow (Claude Code Haiku) |
| `packaging/` | `Dockerfile` (the prepared `verstehen-build` Arch image), `build.sh`, `container.sh`, `compile.sh`, `PKGBUILD`, `smoke.py`, the desktop entry, and `android.sh` (the `make android-*` targets) |
| `.github/workflows/ci.yml`, `release.yml` | CI on PRs and pushes to `main`; releases on a `vX.Y.Z` tag (the Arch package, then the signed Android `.apk`) |
| `.claude/skills/verify/SKILL.md` (also `.agents/skills/verify`) | the verify skill: how to run flows and what evidence to keep |

## How it works

- **Checks are code rules, not prose.** Every custom check's message says what to do instead.
  Corrections that a tool could catch become checks.
- **9-area test separation (`tools/test_areas.py`).** Backend tests live under
  `backend/tests/<area>/` (plus `tools/tests` under `shell`), frontend Vitest files map to areas
  in `VITEST_GLOBS`, and Playwright flows live under `app/verify/<area>/` across the 9 areas
  (`session`, `teaching`, `jobs`, `sidechat`, `graph`, `providers`, `store`, `sync`, `shell`).
  `tools/test_areas.py --check` enforces that no unmapped or stray test/flow files exist. Passing
  `AREA='...'` to `make check`, `make test`, `make verify`, or `make verify-run` scopes execution
  to those areas; area-scoped pytest runs pass `-m 'not live and not slow'` unless `SLOW=1` is set,
  while full `make check` runs all areas including `@pytest.mark.slow`.
- **The fake model.** `VERSTEHEN_FAKE_MODEL_SCRIPT` enables only the fake account: `fake` streams
  scripted replies (text, thinking, tool calls, errors, delays, usage), `fake-title` serves titles
  and role-tagged worker replies.
- **Verify flows.** Each flow gets its own sidecar, Vite preview of the built SPA, and temporary
  data directory; the fixture saves a final `screenshot.png` and an always-on trace in
  `app/verify-output/` (some flows also save intermediate screenshots), and fails on console
  errors, page errors, and failed requests, except expected HTTP errors and requests a reload
  aborts.
  `make verify-run` reuses an unchanged SPA build behind the build guard.
- **Remote flows.** A flow that declares `test.use({ client: 'remote' })` gets the backend in
  `--server` mode (an admin device minted with `verstehen mint-token`, exposed as `serverAdmin`) and
  a preview of the second SPA build, made with `PUBLIC_VERSTEHEN_CLIENT=remote` and
  `PUBLIC_VERSTEHEN_EXTRA_HOSTS=127.0.0.1` into `app/build-remote` (its own `.svelte-kit-remote`).
  `make verify` builds both SPAs and the rerun guard covers both outputs. The preview proxies `/api`
  to the server, so no test-only CORS origin exists.
- **Android builds** (`packaging/android.sh`, JDK 21 at `/usr/lib/jvm/java-21-openjdk` because
  Capacitor 8 needs it; Android SDK in `~/Android/Sdk`): `make android-setup` installs, from the
  command line with no sudo and no Android Studio, the SDK build tools, platform 36, the emulator,
  the system image, and the `Galaxy_S24` (360×780 CSS px) and `Galaxy_Tab_S9` (800×1280) virtual
  devices; it is idempotent. `make android-debug` builds the SPA with
  `PUBLIC_VERSTEHEN_CLIENT=android` and `PUBLIC_VERSTEHEN_EXTRA_HOSTS=10.0.2.2` (release: the same
  client and no extra hosts, whatever the shell has set) into a freshly emptied `app/build-android`,
  a third output besides the verify builds' `build` and `build-remote`, syncs Capacitor, runs the JVM unit test, and writes
  `dist/verstehen-<version>-debug.apk`. `make android` writes the release `.apk`, signed when
  `~/.config/verstehen/android-release.jks` and its password file exist (or `VERSTEHEN_ANDROID_KEYSTORE*`
  are set, as in CI), otherwise unsigned with a warning. `make android-key` creates that key once and
  prints the `gh secret set` commands for `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, and
  `ANDROID_KEY_ALIAS`; agents never run it or read the key.
- **Emulator loop for agents** (the verify skill has the commands): a fake-model `--server` backend
  on a temporary data directory, a pairing code minted through the API, the debug `.apk` installed
  on a virtual device opened in the T3 Code Device panel, pairing at `10.0.2.2:<port>`, one lesson
  turn, screenshots, and `adb logcat`. WebView DevTools over `adb` inspect the UI.
- **Live verification.** `make verify-live` runs `lesson-first-turn` with the logged-in Claude Code
  on Haiku at low thinking; evidence in `app/verify-live-output/`. It never runs in CI.
- **Packaging.** `make app` builds the PyInstaller onedir sidecar, the pure-Python server bundle
  (`/usr/lib/verstehen/server-bundle/`: wheel + locked `requirements.txt` for SSH server
  provisioning), and the Tauri shell inside the prepared Arch image (Docker volumes cache Cargo,
  npm, and uv), runs the frozen self-check and smoke tests (handshake, token refusal, migrations,
  shutdown), and writes `dist/verstehen-<version>-1-x86_64.pkg.tar.zst`. Neither Chromium nor the
  Claude Code CLI is bundled. `make app-image` refreshes the image.
- **Server provisioning.** The desktop SSH provisioner acquires an exclusive `install.lock`
  for the remote account before staging a new venv beside the live one. The lock stays held
  through deploy and recovery, including SSH reconnects. After an interrupted install that
  cannot safely release it, confirm the install has stopped and recover before removing it.
  Before swapping the venv and service unit, it refuses to proceed if `venv.prev`, `unit.prev`,
  or `rollback.pending` remains. It accepts a healthy response only from the invocation systemd
  reports for the installed unit, with the laptop's schema version. If SSH drops, the provisioner
  reconnects to verify before deciding whether to roll back. If it cannot verify, it leaves the
  service and recovery files in place. Rollback checks the previous wheel's migrations before
  and after stopping the attempted service. It keeps recovery files until the restored unit owns
  the listener and answers the health check.
- **CI** (`ci.yml`) runs `make setup`, `make check`, and `make verify` on GitHub-hosted Ubuntu and
  uploads `app/verify-output` on failure. Flows never retry, in CI or locally.
- **Releases** (`release.yml`): bump the versions in `backend/pyproject.toml`,
  `app/src-tauri/Cargo.toml`, and `app/src-tauri/tauri.conf.json`, merge, then push `vX.Y.Z`; the
  workflow checks the versions, runs `make app`, and publishes a GitHub Release; a second job then
  builds the release `.apk` with the key from the `ANDROID_KEYSTORE_*` secrets and attaches it to
  that release. It checks the secrets first and, when they are missing, skips the Android steps
  with a `::notice::`, so the Arch release still succeeds.

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
