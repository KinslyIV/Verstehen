# Plugins

Owns what runs from `<data dir>/plugins/<id>/`: finding installed plugins, the enable choice, a
plugin's Python backend and JS frontend, the bridge between the two, what a plugin adds to the
prober, teacher, and practitioner, and Settings → Plugins. Plugins are trusted local code with no
sandbox. Desktop only: plugins load only in the desktop app (`Settings.plugins`: the desktop shell, or
`VERSTEHEN_PLUGINS=1` in browser-only mode, which the verify flows set); server mode never loads them
and paired remote devices run none.

LearnHarness spec: LH's plugin API v1 (`docs/plugin-authoring.md` at `069a6a11`; no Part A doc).
Differences are in [decisions](../decisions.md#plugins). Writing a plugin:
[plugin authoring](../plugin-authoring.md).

## Code map

Backend, `backend/src/verstehen/` (`plugins` sits beside `jobs | sidechat | graph` and never imports `session`):

| File | What it holds |
|---|---|
| `plugins/manifest.py` | `PluginManifest` and `validate_package`: LH's manifest rules, checked without running plugin code; the reason an invalid package gives |
| `plugins/loader.py` | `load_backend` (import `dist/<backend>/` as `verstehen_plugins.<id>`), `add_vendor`, `forget_backend` |
| `plugins/context.py` | `PluginContext`: what `activate(ctx)` receives (`expose`, `emit`, `on`, `cleanup`, `register_instructions`, `register_tools`, `register_toolset`) and the registrations it records |
| `plugins/service.py` | `PluginService`: discovery, enable and disable, activation, `call`, `file`, `turn_settled`, and `toolset_for` one agent's turn |
| `store/plugins.py` | `PluginsStore`: `<data dir>/plugins-state.json` (atomic write; a corrupt file is refused and never overwritten) |
| `api/plugins.py` | the `/api/plugins` routes |
| `session/turns.py` | `build_agent` asks `PluginService.toolset_for` and adds the result to the prober, teacher, or practitioner |

Frontend, `app/src/lib/plugins/` (plus the lesson layout, graph page, and Settings):

| File | What it holds |
|---|---|
| `host.svelte.ts` | `PluginHost`: reads `/api/plugins`, activates each active plugin once per window, disposes it when disabled, runs actions, delivers notifications |
| `plugins.svelte.ts` | the window's one `plugins` host; runs only in sidecar mode |
| `runtime.svelte.ts` | `PluginRuntime`: one plugin's views, actions, placements, settings, listeners, cleanups, and abort signal |
| `context.ts`, `types.ts` | `createContext`: the plugin's `ctx` (`backend` proxy, `register*`, `app`, `ui`, `cleanup`); the public types |
| `load-module.ts` | the one dynamic `import()` of a plugin's `main.js` |
| `plugin-view.svelte`, `plugin-actions.svelte`, `plugin-settings-page.svelte`, `plugin-icon.svelte` | a view's mount point, placed actions per surface, a plugin's settings page, and the one place trusted SVG is rendered |
| `ui/widgets.svelte.ts`, `ui/plugin-*.svelte` | `pluginUi`: `mountButton`, `mountBadge`, `mountMarkdown`, `mountSettingsRows`, `openDialog`, `openMenu` |
| `lib/components/settings-plugins.svelte` | Settings → Plugins |
| `routes/(lesson)/plugin/[id]/[view]/+page.svelte` | a plugin view's route; the layout draws its top bar |

## How it works

- **Layout.** `plugins/<id>/dist/` holds what runs: `manifest.json`, `backend/` (a Python package,
  optional `vendor/`), `main.js`, `styles.css`, `assets/`. `plugins/<id>/data/` is the plugin's
  own folder and survives updates and disabling. A symlink anywhere in a package is refused: `dist/`,
  `backend/` and everything under it, `main`, `styles` and the `assets` root.
- **Discovery** (`PluginService.discover`, at startup and on **Refresh**): validate each manifest
  without importing anything; a package that cannot run is listed `invalid` with the reason. New
  plugins start disabled. A plugin whose code is imported or running is not rescanned: changed
  code needs an app restart.
- **Enable state** is `plugins-state.json` (`enabled: {id: bool}`, literal booleans only; a file
  that is unreadable, not UTF-8, or invalid is reported on the Plugins page and never rewritten).
  Enabling activates the backend;
  disabling runs its cleanups (newest first) and keeps `data/`. Starts and stops of one plugin are
  serialized by a per-plugin lock and converge on the latest saved choice: an activation that finds
  the plugin disabled meanwhile closes its own context instead of publishing it. A failing `activate` or cleanup
  marks only that plugin `failed` with the error.
- **Backend activation:** a plugin being started is `activating`. `load_backend` re-checks the
  backend path for symlinks and imports the package once per process, `vendor/` goes on
  `sys.path` while the plugin runs, then `activate(ctx)` runs (sync or async; a returned function is
  a cleanup). MCP toolsets are started right after `activate`, so one that cannot start fails the
  plugin.
- **The bridge.** `@ctx.expose` functions are called by `POST /api/plugins/{id}/call/{name}`: JSON
  in (the function's one parameter), JSON out; an error is a 500 `{error}`, a non-JSON result a
  422, a stopped plugin a 409. The frontend's `ctx.backend.<name>(input)` is a Proxy over that
  route. `ctx.emit(topic, data)` becomes a `plugin-message` notification on `/api/events`;
  the frontend's `onNotification(topic, fn)` hears only its own plugin's. `onResync` fires after
  the event stream reconnects. `ctx.on("turn-settled", fn)` observers run after a turn is saved;
  the frontend's `onAppEvent("turn-settled", fn)` follows the same notification.
- **Agent hooks** (`PluginService.toolset_for(agent, session_id)`, called by `build_agent` once per
  turn for the agent that turn runs, `None` when no plugin registered anything for it). Targets:
  `prober`, `teacher`, `practice` (the practitioner). Tool factories receive
  `PluginTurnContext(session_id, agent)` and return tools; toolsets are added as they are. Each
  plugin is one `PluginToolset` (a `WrapperToolset`) and all plugins one `PluginToolsets` (a
  `CombinedToolset`, `plugins/toolsets.py`), the only toolset the agent gets from plugins, in id
  order. `for_run` and `for_run_step` reach every plugin's toolsets, and the turn lists and calls
  the ones they resolve. **Instructions** are not part of the prompt text: `PluginToolsets.get_instructions`
  returns each admitted plugin's `register_instructions` text, and Pydantic AI sends them with the
  agent's own (the Claude Code transport sends them in its system prompt like any other).
- **Admission.** As in LearnHarness, a plugin is admitted whole or not at all. At the turn's first
  tool listing (`PluginToolsets.admit`, shared by every copy of the toolset through a `PluginTurn`)
  each plugin in id order is listed once; one whose factory raised, whose listing raised, or that has
  a tool name from `plugins/reserved.py` (every built-in tool name for every role, setting and
  provider; a test builds the real tools and fails if one is missing) or an earlier admitted
  plugin's, adds no tools and no instructions to that turn and gets `Added nothing to a <agent> turn:
  …` in `PluginInfo.warnings`; a clean later turn clears it. Admission and name ownership do not
  change during the turn: a later listing that fails offers no tools but keeps the plugin admitted.
- **Fencing.** Each listing and call is an operation of the plugin's `PluginContext`. Disabling
  cancels the operations in flight and waits for them before running cleanups, so an MCP process is
  gone when disable returns. A listing or call that begins after the plugin stopped, or whose
  result arrives after, is dropped: no tools are offered and the call is a failed tool result
  (`Plugin <id> is no longer running`). A turn never enters a plugin's MCP toolset (the context owns it).
- **Tool boundary.** A plugin tool that raises is logged on the plugin and returned to the model as a
  failed tool result (`Tool <name> failed: …`, also shown as a plugin warning); the turn goes on.
  `ModelRetry`, `ToolFailed`, deferral and cancellation pass through.
- **Frontend activation.** `PluginHost.sync()` (serialized) reads `/api/plugins` and reconciles
  without waiting for any activation: a new active plugin with `main` gets a runtime at once and an
  activation queued behind its earlier activation or cleanup (one queue per plugin, so a slow plugin
  holds up only itself). The activation adds the `styles` link, imports `/api/plugins/{id}/files/{main}`
  and calls its `activate(ctx)`. A plugin that throws, or whose module has no callable `activate`,
  fails alone (`runtime.failure`, shown in Settings). Disabling aborts `ctx.signal` and drops the
  registrations immediately, then runs cleanups newest first on that queue. Everything on `ctx`
  is bound to the activation: `ctx.backend` calls carry the activation's signal and reject if the
  activation ended meanwhile (also when the reply arrives late), registrations, `ctx.app` navigation,
  `onResync` and `ctx.cleanup` from an ended activation throw, and `ctx.ui` widgets are also disposed
  when the activation ends. A widget listens to its own signal and the activation's and detaches both
  however it ends (dismissed, disposed, or either signal aborted).
- **Tool calls in the thread.** A tool call whose name is not a built-in tool (`built-in-tools.ts`,
  the same list as `plugins/reserved.py`) renders as a collapsed card that expands to its input and
  result or error, also after the plugin is removed. Built-in tools keep their own rules.
- **Surfaces.** A **view** renders in the host's viewport at `/plugin/{id}/{view}`; the host draws
  the top bar. An **action** is registered, then **placed**: `sidebar` (under Knowledge graph),
  `graph` (the graph strip), or `top-bar` for chosen session kinds (`teaching`, `practice`) or for
  the plugin's own views. A failing action shows a dismissible banner. **Settings** is a per-plugin
  page under Settings → Plugins (`?section=plugins&plugin=<id>`): rows, or a `mount`. Each mount of a
  view or settings page gets its own child container; the host logs a cleanup that throws or rejects, also
  one returned after the page was left.
- **Served files.** `GET /api/plugins/{id}/files/{path}` serves only the manifest's `main` and
  `styles` and anything under `assets/`, of an active plugin, each segment a plain name. Every request
  re-checks the plugin folder, `dist/`, and each segment for symlinks and that the resolved file is
  inside `dist/`. The manifest refuses a `backend` folder named `assets`, `manifest.json`, or the
  `main` or `styles` entry.
- **Startup and shutdown.** Discovery is synchronous and quick; persisted activations then run as
  host-owned tasks, so a slow or hanging `activate` never delays the API (the plugin shows
  `activating`, and `plugins-changed` is published when it settles). Disabling or shutting down
  cancels an activation in progress and closes its context, entered toolsets included. A plugins
  folder that cannot be read (say a regular file) is reported as `PluginList.error` on the Plugins
  page and the app starts. On shutdown the session runtimes stop first, so no running turn can call
  a plugin's tool after its cleanup. **Refresh** takes each plugin's lock before replacing or
  keeping its package and reads the enable choice inside it, so a concurrent disable always wins.

## Data and events

| What | Where |
|---|---|
| Enable choices | `<data dir>/plugins-state.json` (not synced) |
| Plugin code and its data | `<data dir>/plugins/<id>/dist/`, `…/data/` (not synced) |
| Routes | `GET /api/plugins`, `POST /api/plugins/refresh`, `PUT /api/plugins/{id}/enabled`, `POST /api/plugins/{id}/call/{name}`, `GET /api/plugins/{id}/files/{path}` |
| Notifications | `plugins-changed` (list or status changed: refetch `/api/plugins`), `plugin-message` (`plugin_id`, `topic`, `data`) |

Plugin tool calls are saved in the transcript like built-in ones; an old session reads the same
after its plugin is removed.

## Collaborators

`session/turns.py` is the only caller of `toolset_for`; `app.py` builds `PluginService` before
`TurnService` and passes it `publish` callbacks for `plugins-changed` and `plugin-message`, as
`jobs` gets `wake_session`.

## Traps

- **Changed plugin code needs a restart** (the backend module is cached; `main.js` is imported
  once per window and cached by the browser until reload).
- **MCP servers in the packaged app.** `sys.executable` there is the `verstehen` binary, so an MCP
  toolset should run an external command (`npx`, `uvx`, a binary), not a Python script.
- **Pydantic AI 2.70:** MCP is `pydantic_ai.mcp.MCPToolset` over `fastmcp-slim`; `MCPServerStdio` no
  longer exists. PyInstaller does not see `mcp`/`fastmcp` imports, so `verstehen.spec` collects them.
- **`practice` means the practitioner;** a session's `kind` is `teach|practice` in the API but
  `teaching|practice` in plugin placements, as in LearnHarness.
- **`{@html}`** is used once, in `plugin-icon.svelte`, for trusted SVG from the plugin.

## Tests

`backend/tests/plugins/` (`test_discovery.py`, `test_lifecycle.py`, `test_bridge.py`,
`test_agent_hooks.py`) with fixture plugins in `backend/tests/fixtures/plugins/`;
`app/src/lib/plugins/**/*.test.ts`; flows in `app/verify/plugins/` run against the `hello` fixture
plugin, which the `plugins` option of the verify fixture copies into the flow's data directory.
