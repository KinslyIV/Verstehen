# Writing a Verstehen plugin

A short guide for plugin authors. How the host works is in [architecture/plugins](architecture/plugins.md);
the working example is [`backend/tests/fixtures/plugins/hello`](../backend/tests/fixtures/plugins/hello/dist).
Plugins are trusted local code with no sandbox: a backend runs inside Verstehen with access to
your files and network. The API is modeled on LearnHarness's plugin API v1.

## Package

Install a plugin by putting its built folder at `<data dir>/plugins/<id>/dist/` (the Plugins
page shows the folder), then **Refresh** and enable it. Plugin code changes need an app restart.

```
plugins/<id>/
  dist/
    manifest.json
    backend/__init__.py      optional; may have vendor/ with pure-Python packages
    main.js                  optional ES module
    styles.css               optional; needs main.js
    assets/                  files the frontend may load
  data/                      yours; kept when the plugin is updated or disabled
```

`manifest.json`: `apiVersion` (1), `id` (lowercase-hyphen, the folder name), `name`, `version` and
`minAppVersion` (`x.y.z`); optional `description`, `author`, `backend` (the folder name),
`main`, `styles`. At least one of `backend` and `main`. Anything else invalid is listed with the
reason and never runs.

## Backend

```python
def activate(ctx):  # sync or async; may return a cleanup function
    @ctx.expose
    def greet(name): ...  # the frontend calls ctx.backend.greet("Ada")

    ctx.register_instructions(["teacher"], "Prompt text.")
    ctx.register_tools(
        ["teacher"], lambda turn: [my_tool]
    )  # turn.session_id, turn.agent
    ctx.register_toolset(["prober"], toolset)  # e.g. a Pydantic AI MCPToolset
    ctx.on("turn-settled", lambda session_id: ...)
    ctx.emit("changed", {"n": 1})  # frontend onNotification("changed", ...)
    ctx.cleanup(lambda: ...)
```

- `ctx.id`, `ctx.directory` (`dist/`), `ctx.data_directory` (`data/`, created for you).
- Exposed functions take at most one JSON value and return JSON; they may be sync or `async` (sync
  handlers run in a worker thread so they do not block the app). A call still running when the
  plugin is disabled is cancelled (or its late worker-thread result is discarded), and its reply is a 409.
- A synchronous `activate` runs in a worker thread, so it may block; `ctx.register_*`, `ctx.on`,
  `ctx.cleanup` and `ctx.emit` are safe from it. An `async def activate` runs on the app's event
  loop and must not block (use `await`, `asyncio.to_thread` or a sync `activate`).
- Agent names: `prober`, `teacher`, `practice` (the practitioner). Hooks only add; a tool whose name
  clashes with any built-in tool or another plugin's tool is refused, and your plugin adds no tools
  and no instructions to that turn (Settings → Plugins shows the warning). A plugin that is disabled
  mid-turn stops at once: its async tool calls in flight are cancelled. A synchronous tool or sync
  `@ctx.expose` function runs in a worker thread and is not forcefully interrupted by disable (as in
  LearnHarness): keep it quick, or make it `async`. A tool that raises gives the model an error
  message; the turn goes on.
- Dependencies: the standard library, what Verstehen bundles, and pure-Python code in
  `backend/vendor/`. Nothing is installed for you. An MCP toolset in the packaged app should run an
  external command, not a Python script.

## Frontend

`main.js` exports `activate(ctx)` (sync or async; may return a cleanup). It runs once per window;
`ctx.signal` aborts when the plugin is disabled.

```js
export function activate(ctx) {
  ctx.registerView({ id: 'main', name: 'Title', mount(container, signal) { /* ... */ } });
  ctx.registerAction({ id: 'open', name: 'Open', icon: '<svg…/>', run: (context) => ctx.app.openView('main') });
  ctx.placeAction({ id: 'in-sidebar', actionId: 'open', location: 'sidebar' }); // 'graph' | 'top-bar'
  const settings = ctx.registerSettings({ rows: [...] }); // returns { update({ rows }), dispose() }; or { mount(container, signal) } -> () => void
}
```

- Placements: `sidebar`, `graph`, and `top-bar` with `sessions: ['teaching', 'practice']` or
  `views: ['<view id>']`. An action's `run` gets where it was clicked (`context.sessionId` for a
  session). `ctx.refreshActions()` re-reads `disabled`.
- `ctx.backend.<name>(input)`; `ctx.onNotification(topic, fn)` and `ctx.onResync(fn)` (delivered
  across the whole window, including `/settings`; `onResync` fires when the event stream
  reconnects); `ctx.onAppEvent('turn-settled', fn)`; `ctx.app` (`pathname`, `openSession`,
  `openHome`, `openView`, `openSettings`); `ctx.cleanup(fn)`.
- `ctx.ui` widgets match the app's look: `mountButton`, `mountBadge`, `mountMarkdown`,
  `mountSettingsRows`, `openDialog` (`content` may be an `HTMLElement` or a sync/async
  `(container, signal)` mount returning an optional sync/async cleanup), `openMenu` (each returns
  `{ update(props), dispose() }`). Pass `{ signal }`; aborting it disposes the widget.
- Files load from `/api/plugins/<id>/files/...`: `main`, `styles`, and `assets/` (served from the
  bytes snapshotted when the plugin was first activated).
