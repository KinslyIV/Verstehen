# Plugins: a plugin system for Verstehen

> Status: **overview approved by the user (2026-11-25); steps drafted.** Branch: `plugins` off
> `dev` (not created yet).

## Overview

- **What changes:** Verstehen loads community plugins from `<data dir>/plugins/<id>/`. A plugin
  has an optional Python backend and an optional JS frontend, each exporting `activate(ctx)`.
  The host owns discovery, enable state, lifetimes, the bridge between the two halves, and where
  contributions appear; plugins own their data, prompts, tools, and UI. Modeled on LearnHarness's
  plugin API v1 (`069a6a11`, `docs/plugin-authoring.md`); no LearnHarness plugin is ported.
- **Pieces:**
  1. **Discovery and enable state** (`PluginService`, `plugins_store`): read each
     `dist/manifest.json`, validate it without running code, list invalid or incompatible
     packages with the reason. New plugins start disabled; choices live in
     `<data dir>/plugins-state.json`. Disabling never deletes `data/`.
  2. **Backend activation** (`PluginContext`): import `dist/<backend>/` under a unique module name
     with its `vendor/` on the import path, call `activate(ctx)` once per backend, run cleanup on
     disable or shutdown. A failing plugin gets a visible error; the rest of the app keeps working.
  3. **Bridge:** `@ctx.expose` functions are reachable from the frontend as
     `ctx.backend.<name>(input)` through one host route (JSON in, JSON out, token-checked).
     `ctx.emit(topic, data)` reaches the frontend's `onNotification` over the existing event
     stream; `onResync` fires after a reconnect. `ctx.on("turn-settled", fn)` observes turns.
  4. **Agent hooks:** `register_instructions`, `register_tools`, `register_toolset` for `prober`,
     `teacher`, `practice` (= the practitioner). Added per matching turn next to the built-in
     tools, only adding, never replacing; a colliding name is refused and that plugin contributes
     nothing for the turn. Toolsets cover MCP servers (Pydantic AI `MCPServerStdio` /
     `MCPServerStreamableHTTP`), started on activate and stopped on disable.
  5. **Frontend activation:** load `dist/main.js` (and `styles.css`) as an ES module once per
     window, call `activate(ctx)`. Hooks: `registerView` (a plugin page; the host owns its top
     bar and scrolling), `registerAction` + `placeAction` (sidebar, graph strip, session or view
     top bar), `registerSettings` (a Settings page per plugin), `ctx.app` navigation, and
     `ctx.ui`: `mountButton`, `mountBadge`, `mountSettingsRows`, `mountMarkdown`, `openDialog`,
     `openMenu`.
  6. **Settings → Plugins:** list, enable/disable, errors, the plugins folder path, and refresh,
     as in LearnHarness's community plugins page. Changed plugin code needs an app restart.
- **What the user notices:** a Plugins page in Settings; enabled plugins add buttons, pages,
  settings pages, and tools the tutor can call. Nothing changes until a plugin is installed and
  enabled.
- **Non-obvious effects:** plugins are trusted local code with no sandbox, as in LearnHarness.
  No migration of existing data. Android, server mode, and sync are unchanged: plugins are not
  installed on the server, and `plugins/` and `plugins-state.json` are not synced. Plugin tool
  calls are saved in the transcript like built-in ones, so old sessions read correctly after a
  plugin is removed.
- **Later (not in this plan):** code-block and tool renderers, question/problem types,
  submission interceptors, learning-data reads, inference, managed agents, workers, documents,
  more `ctx.ui` widgets, core (app-shipped) plugins, Android/server mode.

## User decisions

- **Languages:** Python backend + JS/TS frontend, not JS-only via a Node sidecar or
  PythonMonkey, not Python-only declarative UI.
- **Platforms:** desktop only for now; no server install, plugin data sync, or phone UI.
- **Bridge transport:** HTTP through one host route, not `QWebChannel`; plugin authors write no
  endpoints.
- **Bridge API:** backend `@ctx.expose` on a function, frontend `ctx.backend.<name>(input)`
  through a JS Proxy (difference from LearnHarness's `ctx.handle` / `ctx.call`).
- **Toolset hook:** in the first version (difference from LearnHarness, which has no MCP or
  toolset hook).
- **Backend dependencies:** the standard library, Verstehen's bundled packages, and pure-Python
  code vendored inside the plugin folder (put on the import path by the host). The host installs
  nothing, as in LearnHarness.
- **Agent targets:** `prober`, `teacher`, `practice`, as in LearnHarness; the host maps
  `practice` to the practitioner agent.
- **Plugin kinds:** community only, under `<data dir>/plugins/<id>/`; core (app-shipped)
  plugins come later.
- **Layout:** as in LearnHarness: `plugins/<id>/dist/` holds what runs (`manifest.json`,
  `backend/` Python package with optional `vendor/`, `main.js`, `styles.css`, `assets/`);
  sibling `plugins/<id>/data/` holds records and survives updates.
- **Manifest:** LearnHarness's fields and rules. Required `apiVersion` (our API, starting at 1),
  `id` (lowercase-hyphen, equals the folder name), `name`, `version`, `minAppVersion` (numeric
  `x.y.z`); optional `description`, `author`, `backend` (Python package folder in `dist/`),
  `main` (`.js`), `styles` (`.css`, needs `main`); at least one of `backend` / `main`. Invalid or
  incompatible packages are listed with the reason and never run.
- **Names:** host `PluginService` / `plugin_service`, `plugins_store` (enable choices in
  `<data dir>/plugins-state.json`), `PluginContext` (backend ctx). Backend ctx: `id`,
  `directory`, `data_directory`, `expose`, `emit`, `on`, `register_instructions`,
  `register_tools`, `register_toolset`, `cleanup`. Frontend ctx: `backend`, `registerView`,
  `registerAction`, `placeAction`, `registerSettings`, `refreshActions`, `onNotification`,
  `onResync`, `onAppEvent`, `app` (`pathname`, `openSession`, `openHome`, `openView`,
  `openSettings`), `ui`, `cleanup`, `signal`.
- **`ctx.ui`:** `mountButton`, `mountBadge`, `mountSettingsRows`, `mountMarkdown`,
  `openDialog`, `openMenu`, with LearnHarness's props / handle shape (`update`, `dispose`,
  per-mount signal).
- **Scope:** the first version covers exactly the overview's pieces 1–6.

## Structure afterwards

```
backend/src/verstehen/
  store/plugins.py        PluginsStore: plugins-state.json (atomic write, corrupt file refused)
  plugins/                new package, layer beside jobs | sidechat | graph
    manifest.py           PluginManifest (Pydantic) + validate_package(path) → manifest | reason
    context.py            PluginContext: the backend ctx, records registrations
    service.py            PluginService: discover, enable/disable, activate, cleanup,
                          call(name), contributions(role), observers of app events
  api/plugins.py          /api/plugins routes (list, refresh, enabled, call, files)
  session/turns.py        build_agent adds plugin instructions, tools, toolsets
  session/events.py       Notification gains plugins-changed and plugin-message
app/src/lib/plugins/
  host.svelte.ts          load main.js per enabled plugin, build ctx, keep registries in runes
  context.ts              frontend ctx: backend proxy, register*, app, cleanup, signal
  ui/                     the six ctx.ui widgets (mount into a container, update, dispose)
  plugin-view.svelte      renders a registered view body
  plugin-actions.svelte   renders placed actions for one location
app/src/routes/(lesson)/plugin/[id]/[view]/+page.svelte
app/src/lib/components/settings-plugins.svelte   Settings → Plugins + per-plugin pages
```

The new layer order: `desktop → api | lh_import → sync → session → jobs | sidechat | graph |
plugins → teaching | providers → store`. `plugins` never imports `session`; session hands it
`publish` (for `ctx.emit` and `plugins-changed`) at startup, as `jobs` gets `wake_session`.

## Steps

Each step is one commit on `plugins`, with `make check AREA='plugins …'` passing. A new test
area `plugins` (`backend/tests/plugins/`, `app/src/lib/plugins/**/*.test.ts`,
`app/verify/plugins/`) is added to `tools/test_areas.py` in step 1. Fixture plugins live in
`backend/tests/fixtures/plugins/<id>/dist/` and are copied into a temporary
`VERSTEHEN_DATA_DIR`.

### 1. Manifest, store, discovery

- `PluginManifest` with LearnHarness's rules (`069a6a11` `docs/plugin-authoring.md`, "Package
  and installation"): `apiVersion == 1`, `id` lowercase-hyphen and equal to the folder name,
  numeric `x.y.z` `version` and `minAppVersion` (compared with Verstehen's version), entry
  names are plain names at the root of `dist/` (`backend` a folder with `__init__.py`, `main`
  `.js`, `styles` `.css` only with `main`), at least one entry. Symlinked `dist/` refused.
- `PluginsStore` (`store/plugins.py`, copying `SettingsStore`'s read/write shape but on a JSON
  file like `ModelCatalogStore`): `{ "enabled": { "<id>": bool } }`; missing → empty; corrupt →
  error, never overwritten (LH).
- `PluginService.discover()` → `PluginInfo(id, name, version, description, author, enabled,
  status: "disabled" | "active" | "invalid" | "failed", error, warnings)`. New plugins default to
  disabled. Server mode (`settings.desktop` false) discovers nothing.
- Tests: valid package listed disabled; each manifest rule refused with its reason and never
  imported; corrupt state file refused; enable choice survives a new `PluginService`.

### 2. Backend activation and lifecycle

- Import `dist/<backend>/` with `importlib` under `verstehen_plugins.<id_with_underscores>`,
  with `dist/<backend>/vendor/` on `sys.path` when present. Call `activate(ctx)` (sync or
  async); a returned callable is cleanup, as is each `ctx.cleanup(fn)` (run in reverse order).
- Enable activates now; disable runs cleanup and drops every registration; refresh discovers new
  folders; changed code of an imported plugin needs a restart (module cache, as in LH). Shutdown
  (the `create_app` lifespan) runs every cleanup.
- An exception in import, `activate`, or cleanup marks the plugin `failed` with the message;
  other plugins and the app continue.
- `ctx.id`, `ctx.directory` (`dist/`), `ctx.data_directory` (`plugins/<id>/data/`, created on
  first activation).
- Tests: activate/cleanup order, async activate, failing activate isolated, disable drops
  registrations, data folder kept on disable.

### 3. API, bridge, events

- `api/plugins.py` (copy the `get_session` route pattern): `GET /api/plugins`,
  `POST /api/plugins/refresh`, `PUT /api/plugins/{id}/enabled`,
  `POST /api/plugins/{id}/call/{name}` (JSON body in, JSON out; 404 unknown plugin or name,
  409 plugin not active, 422 non-JSON result, the plugin's exception text as 500 detail),
  `GET /api/plugins/{id}/files/{path}` (only the manifest's `main`, `styles`, and `assets/**`;
  never `backend/` or `data/`; path traversal refused).
- `@ctx.expose` / `@ctx.expose(name=...)`: name defaults to the function name; sync or async;
  duplicate names refused at registration.
- `Notification` gains `plugins-changed` (after discover/enable/disable/failure) and
  `plugin-message` (`plugin_id`, `topic`, `data`) for `ctx.emit` (LH event names,
  `docs/learnharness/storage-and-events.md`). `ctx.on("turn-settled", fn)` gets the session id;
  an observer's exception is logged on the plugin, never breaks the turn.
- Tests: call round trip, each error status, files route allowlist, emit reaches `/api/events`,
  `turn-settled` observer runs after the turn is saved.

### 4. Agent hooks and toolsets

- `ctx.register_instructions(agents=[...], text=...)`, `ctx.register_tools(agents=[...],
  create=fn)` (`create(PluginTurnContext(session_id, agent))` returns Pydantic AI `Tool`s or
  functions), `ctx.register_toolset(agents=[...], toolset=...)`. `agents` ⊆ `prober`,
  `teacher`, `practice`; anything else refused at registration.
- `PluginService.contributions(agent, session_id)` → instructions, tools, toolsets, in sorted
  plugin-id order. `TurnService.build_agent` appends the instructions to the composed prompt
  (separated like the other sections) and passes tools and toolsets to `build_prober`,
  `build_teacher`, `build_practitioner` (new `extra_toolsets` parameter on the three builders).
- **Collisions (LH "Existing agents" section):** a plugin whose tool name collides with a built-in
  tool or an earlier plugin's tool contributes nothing to that turn and gets a warning on its
  `PluginInfo`; a later clean turn clears it. A `create` exception does the same.
- **Toolset lifetime:** the host enters each registered toolset (`async with`) on activation and
  exits it on cleanup, so an MCP server runs while the plugin is enabled; a toolset that fails to
  start marks the plugin `failed`. Add the `mcp` extra to `pydantic-ai-slim` (the `mcp` package
  is already in `uv.lock`) and check the PyInstaller build includes it.
- Plugin tool calls and results are saved and shown like any other tool; no new entry type.
- Tests (FunctionModel): a plugin tool is offered to the chosen agent only and its result saved;
  instructions appear in the system prompt; a collision drops the plugin's whole contribution
  with a warning; a stdio MCP fixture server (FastMCP script in `tests/fixtures/`) is started on
  enable, its tool called in a turn, and stopped on disable; Claude Code transport receives a
  toolset tool (unit test on `_request.py` tool definitions).

### 5. Frontend host, views, actions, settings, `ctx.ui`

- `lib/plugins/host.svelte.ts`: on app start and on `plugins-changed`, fetch `/api/plugins`;
  for each active plugin with `main`, add its `styles` link and `import()` the module from the
  files route; call `activate(ctx)` once per window; on disable abort `ctx.signal` and run
  cleanups. An exception marks it failed in the UI, never breaks the page.
- `ctx.backend` is a Proxy whose properties call `POST /api/plugins/{id}/call/{name}` through a
  new `lib/api/client.ts` function (`callPlugin`); errors reject with the server's detail.
  `onNotification(topic, fn)` filters `plugin-message`; `onResync` fires after the event stream
  reconnects; `onAppEvent("turn-settled", fn)`.
- `registerView` + route `(lesson)/plugin/[id]/[view]`: the host draws the top bar and the
  bounded scroll viewport; `mount(container, signal)` draws the body; leaving aborts the signal
  (LH "Frontend lifecycle and navigation").
- `registerAction` / `placeAction` / `refreshActions` with locations `sidebar`, `graph`,
  `top-bar` (`sessions: ["teaching", "practice"]` and/or `views`); the host owns the button,
  busy state, and error toast; the action context follows LH's table, without `view` (the
  session snapshot is later).
- `registerSettings`: one page per plugin under Settings → Plugins.
- `ctx.app`: `pathname`, `openSession`, `openHome`, `openView`, `openSettings`.
- `ctx.ui`: `mountButton`, `mountBadge`, `mountSettingsRows`, `mountMarkdown` (the real
  pipeline, no plugin fences), `openDialog`, `openMenu`; each returns `{ update, dispose }` and
  honours the per-mount signal; built from shadcn-svelte components with `mount()`.
- Settings → Plugins (`settings-plugins.svelte`): list with name, version, description, status,
  error and warnings, an enable switch, the folder path, and Refresh; the trust note from LH's
  community page.
- Tests (Vitest browser): ctx proxy calls the route; activate/cleanup on enable/disable; a
  throwing plugin is isolated; each widget mounts, updates, disposes.

### 6. Verify flows, fixture plugin, docs

- Fixture plugin `hello` (backend: one exposed function and one teacher tool; frontend: a view,
  sidebar and session top-bar actions, a settings page with `mountSettingsRows`), copied into
  the verify data dir. The MCP toolset is covered by step 4's backend test, not a flow.
- Flows in `app/verify/plugins/`: `plugins-settings` (listed disabled → enable → active, its
  settings page), `plugins-view-actions` (sidebar action opens the view, which calls the backend
  and shows the result; top-bar action in a session), `plugins-tool` (fake-model script calls the
  plugin tool; result shown in the transcript).
- Docs: `docs/architecture/plugins.md` (area doc following `architecture/session.md`), area map
  and package order in `docs/architecture.md`, `docs/feature-map.md` entries for the three flows,
  `docs/patterns.md` entry for the fixture plugin, `docs/decisions.md` (the toolset hook and the
  `@ctx.expose` bridge as differences from LH), `docs/roadmap.md` (plugins no longer deferred;
  later groups listed), `docs/status.md`. A short `docs/plugin-authoring.md` for plugin authors.
