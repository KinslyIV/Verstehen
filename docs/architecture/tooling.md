# Tooling and packaging

Owns how the code is checked, verified, run, built, and released: the Makefile, the custom checks,
the fake model, the verify flows, the console entry, the desktop entry and self-check, the Arch package, the Android app build and its emulator loop, and CI.

## Where things run

| | Pixal (Ubuntu home server) | Laptop (Arch) |
|---|---|---|
| Role | agents write, test, verify, and build | runs the installed app; agents may use it through a T3 linked environment when Pixal is busy |
| Browser | Playwright's own Chromium for `make verify` and the server-mode demo tests; PySide6 runs the desktop offscreen in tests | the app's own QtWebEngine (Chromium); Playwright only in a `--server` run |
| Real data | none | `~/.local/share/verstehen`: always set `VERSTEHEN_DATA_DIR` elsewhere |

## Code map

| Path | What it holds |
|---|---|
| `Makefile` | `setup`, `check` (= `check-backend` + `check-frontend`), `test`, `fmt`, `dev`, `verify`, `verify-run`, `verify-live`, `api-types`, `lock-migrations`, `app`, `app-image`, `android-setup`, `android-debug`, `android`, `android-key` (`AREA='...'` scopes test and flow targets to the 9 architecture areas; `SLOW=1` includes `@pytest.mark.slow` in area-scoped pytest runs) |
| `tools/` | custom checks and runners, each tested in `tools/tests/`: `check_comments.py` (≤ 3 lines per comment block), `check_migrations.py` (migration lock), `check_feature_map.py` (every verify flow is in the feature map), `test_areas.py` (enforces 9-area organization across `backend/tests/<area>/`, frontend Vitest globs, and `app/verify/<area>/`, and routes `pytest`, `vitest`, and `verify`), `api_types.py` (generated types are fresh), `verify_build.py` (the SPA build guard), `dev.py` (`make dev`) |
| `ruff.toml`, `*/ruff.toml`, `pyrefly.toml`, `backend/pyproject.toml` | Python 3.15 (`backend/.python-version`), heavy dependencies imported inside the functions that use them (guarded by `backend/tests/shell/test_startup_imports.py`; PEP 810 `lazy` is banned by `ruff` `ban-lazy`), lint, banned APIs per package, types, import-linter layers, pytest (`live` and `slow` markers; xdist `-n auto` via `tools/test_areas.py`) |
| `app/eslint.config.*`, Prettier, Vitest | frontend lint with boundaries, format, unit and browser-mode component tests |
| `backend/src/verstehen/arguments.py`, `cli.py`, `config.py` | the command line (`parse_arguments`, parsed once; the mode comes from `--server` or `VERSTEHEN_SERVER=1`), the console entry `verstehen.cli:main`, the browser-only and `--server` backend (`serve`, logging, `uvicorn_config`), the `import-learnharness`, `mint-token`, and `desktop` subcommands, and environment settings |
| `backend/src/verstehen/desktop/` | the Qt shell (`shell.py`, `server.py`, `demo_runner.py`, `links.py`, `pages.py`) and `__main__.py` (`python -m verstehen.desktop`, which runs `verstehen.cli:main` with `desktop` appended); [frontend shell](frontend-shell.md), [jobs](jobs.md) |
| `backend/src/verstehen/self_check.py` | `verstehen --self-check`: resvg, PDFium, Pillow, `regex`, the prompts, an offline demo page (`qt-demo` in the desktop bundle, `playwright` and `headless` in the server bundle, chosen by whether PySide6 imports), the Claude CLI |
| `backend/src/verstehen/providers/fake.py`, `app/verify/scripts/*.json` | the scripted fake model and its reply scripts |
| `app/verify/<area>/*.flow.ts`, `fixtures.ts`, helpers | fake-model Playwright flows grouped by the 9 architecture areas; `playwright.config.ts` |
| `app/verify-live/`, `playwright.live.config.ts` | the one real-model flow (Claude Code Haiku) |
| `backend/packaging/` | `verstehen.spec` (PyInstaller) and `entrypoint.py` (the frozen entry) |
| `packaging/` | `Dockerfile` (the prepared `verstehen-build` Arch image), `build.sh`, `container.sh`, `compile.sh`, `PKGBUILD`, `smoke.py`, `icons/` (the package icons and the window icon), the desktop entry, and `android.sh` (the `make android-*` targets) |
| `.github/workflows/ci.yml`, `release.yml` | CI on PRs and pushes to `main` (plus the debug `.apk` on PRs); releases on a `vX.Y.Z` tag (the Arch package, then the signed Android `.apk`) |
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
- **Heavy libraries load on first use, in every mode.** Each is imported inside the function
  that uses it; PEP 810 `lazy` is banned because PySide6 (shiboken6) replaces `__import__` and
  leaves some lazy names as unresolved proxies, depending on import order.
  `test_startup_imports.py` checks server start and the real desktop window (offscreen) load none
  of them, and that one still loads on use. No pytest process imports PySide6: Qt tests run a probe
  script in a subprocess (`backend/tests/shell/desktop_probe.py`,
  `backend/tests/jobs/desktop_demo_probe.py`), with `QT_QPA_PLATFORM=offscreen`.
- **Two extras.** `desktop` is `PySide6-Essentials` and `PySide6-WebEngine`; `server` is
  Playwright. The dev environment has both (`verstehen[desktop,server]`), so tests cover both
  runners; the desktop bundle has no Playwright (`excludes` in `verstehen.spec`), and the server
  bundle has no PySide6.
- **Verify flows.** Each flow gets its own backend, Vite preview of the built SPA, and temporary
  data directory; the fixture saves a final `screenshot.png` and an always-on trace in
  `app/verify-output/` (some flows also save intermediate screenshots), and fails on console
  errors, page errors, and failed requests, except expected HTTP errors and requests a reload
  aborts.
  `make verify-run` reuses an unchanged SPA build behind the build guard.
- **Touch and phone flows.** The `mobile-*` flows set `isMobile`, `hasTouch`, and a phone `screen`;
  `verify/touch.ts` sends taps, long presses, drags, and pinches through CDP. The `goesOffline`
  fixture option lets `mobile-reconnect` take the browser offline mid-stream without that failing
  the flow.
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
  `ANDROID_KEY_ALIAS`; agents never run it or read the key. `debug`, `release`, and the `web`
  subcommand hold an exclusive `flock` on `app/.android-build.lock` from the web sync to the `.apk`
  copy, because they share `app/android/app/src/main/assets/public`; a second build prints a notice
  and waits for the first. The lock sits outside Gradle's `build` directory, which `clean` deletes
  (`ANDROID_BUILD_LOCK` overrides the lock path, for tests).
- **Emulator loop for agents** (the verify skill has the commands): a fake-model `--server` backend
  on a temporary data directory, a pairing code minted through the API, the debug `.apk` installed
  on a virtual device opened in the T3 Code Device panel, pairing at `10.0.2.2:<port>`, one lesson
  turn, screenshots, and `adb logcat`. WebView DevTools over `adb` inspect the UI.
- **Live verification.** `make verify-live` runs `lesson-first-turn` with the logged-in Claude Code
  on Haiku at low thinking; evidence in `app/verify-live-output/`. It never runs in CI.
- **Packaging.** `make app` runs in the prepared Arch image (`Dockerfile`: Node, uv, and the Qt
  and Chromium runtime libraries; Docker volumes cache npm and uv). `compile.sh` builds the SPA,
  then `verstehen.spec` freezes one PyInstaller onedir app, `/usr/lib/verstehen/verstehen`
  (`/usr/bin/verstehen` links to it), with PySide6, QtWebEngine, the built SPA (`spa/`), and the
  window icons (`icons/`). Its `shipped` filter drops the Qt parts nothing loads: libraries no
  shipped binary links to (`UNUSED_QT_LIBRARY`), `qml/`, the QML debugger plugins, and every
  translation except English and German (about 170 MB unpacked). `entrypoint.py` points `VERSTEHEN_SPA_DIR` and `VERSTEHEN_ICONS_DIR` at
  them, opens the desktop when run without arguments, and refuses `--server` (server mode runs
  from the server bundle). The pure-Python server bundle (`/usr/lib/verstehen/server-bundle/`:
  wheel + `requirements.txt` exported with `--extra server`, for SSH server provisioning) is built
  next, and `compile.sh` fails if that file names PySide6 or shiboken6
  (`backend/tests/sync/test_server_bundle.py` runs the same export). The frozen app must not
  bundle the Claude Code CLI. `packaging/smoke.py` first checks with `ldd` that every shipped
library finds the Qt libraries it links to, then runs the frozen `--self-check` and starts
  the app offscreen (`QT_QPA_PLATFORM=offscreen`, with `--no-sandbox --disable-gpu` for the smoke
  run only): the window's own API calls must return 200 with the cookie (read from the access
  log), `/` is served, `/api/health` without the cookie is 403, SIGTERM exits 0 with no process
  left in the app's session, and the migrations have run. `makepkg` writes
  `dist/verstehen-<version>-1-x86_64.pkg.tar.zst`; its `depends` lists the Qt and Chromium runtime
  libraries. Neither Chromium nor the Claude Code CLI is bundled. `make app-image` refreshes the
  image.
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
  The generated unit stops within 15 s (`TimeoutStopSec=15`) and the server bounds its graceful
  shutdown to 5 s, so open SSE streams cannot hold the port. The server binds with `SO_REUSEADDR`,
  so later restarts rebind at once; the first upgrade from a version without it waits out Linux's
  60 s TIME_WAIT. The health and rollback waits (90 s) cover the stop, `RestartSec=5`, TIME_WAIT,
  and startup. Device-token checks keep their own 5-attempt budget.
- **CI** (`ci.yml`) runs `make setup`, `make check`, and `make verify` on GitHub-hosted Ubuntu and
  uploads `app/verify-output` on failure. Flows never retry, in CI or locally. On pull requests
  into `main` a second job, `android-debug`, sets up JDK 21 (Temurin) and the Android SDK, runs
  `make android-debug`, and uploads the debug `.apk` as the `verstehen-debug-apk` artifact; it uses
  no secrets.
- **Releases** (`release.yml`): bump the version in `backend/pyproject.toml`, the only version
  file; merge, then push `vX.Y.Z`; the workflow checks the tag against it, runs `make app`, and publishes a GitHub Release; a second job then
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
