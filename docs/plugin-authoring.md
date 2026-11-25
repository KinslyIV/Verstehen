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
- Exposed functions take at most one JSON value and return JSON; they may be `async`.
- Agent names: `prober`, `teacher`, `practice` (the practitioner). Hooks only add; a tool whose name
  clashes with any built-in tool or another plugin's tool is refused, and your plugin adds no tools to
  that turn (Settings → Plugins shows the warning). A tool that raises gives the model an error
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
  ctx.registerSettings({ rows: [...] });   // or { mount(container, signal) }
}
```

- Placements: `sidebar`, `graph`, and `top-bar` with `sessions: ['teaching', 'practice']` or
  `views: ['<view id>']`. An action's `run` gets where it was clicked (`context.sessionId` for a
  session). `ctx.refreshActions()` re-reads `disabled`.
- `ctx.backend.<name>(input)`; `ctx.onNotification(topic, fn)`; `ctx.onResync(fn)`;
  `ctx.onAppEvent('turn-settled', fn)`; `ctx.app` (`pathname`, `openSession`, `openHome`,
  `openView`, `openSettings`); `ctx.cleanup(fn)`.
- `ctx.ui` widgets match the app's look: `mountButton`, `mountBadge`, `mountMarkdown`,
  `mountSettingsRows` (each returns `{ update(props), dispose() }`), `openDialog`, `openMenu`. Pass
  `{ signal }`; aborting it disposes the widget.
- Files load from `/api/plugins/<id>/files/...`: `main`, `styles`, and `assets/`.
