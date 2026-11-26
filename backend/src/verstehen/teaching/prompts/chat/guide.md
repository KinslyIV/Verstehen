# Verstehen App Guide

## overview

Verstehen is an AI learning application with a persistent knowledge graph. It offers three session kinds:
- **Teaching (`teach`)**: Starts with the **Prober** (which brackets the learner's floor and ceiling across dependency strands using graded questions and concludes with `probe_done`), then hands off automatically to the **Teacher** (which builds a dependency DAG with `plan_init`, teaches one step at a time, and verifies each step with predictions and checks).
- **Practice (`practice`)**: Runs the **Practitioner**, which poses self-contained problems (`problem`) with committed model solutions, coaches through a thinking dock using a hint ladder (`R0`–`R5`), and records outcomes and verdicts (`conclude`).
- **Chat (`chat`)**: Runs the **Chat agent** for freeform conversation, inspecting prompts, settings, sessions, folders, and the knowledge graph, and preparing 1-click Launch Cards (`prepare_session`) to start clean Teaching or Practice sessions.

## sessions-and-navigation

- **Starting a session**: Click **Teaching**, **Practice**, or **Chat** at the top of the left sidebar, or switch modes on `/session/new` (`Teach | Practice | Chat`). Right-clicking (or long-pressing on touch) a folder in the sidebar offers **New teaching here**, **New practice here**, and **New chat here**.
- **Sidebar filter & search**: Filter sessions by **Teaching**, **Practice**, **Chat**, or **All**. Use the **Search…** box (`Ctrl+Shift+F` / `Cmd+Shift+F`) to fuzzy-search session titles; arrow keys walk matches and `Enter` opens the selected row.
- **Folders**: Click the folder-plus button beside the **Search…** box to create a folder. Drag sessions or folders to reorganize them, or right-click a session and choose **Move to folder**. Empty folder trees can be deleted from the folder context menu.
- **Keyboard shortcuts**:
  - `Ctrl+B` / `Cmd+B`: Toggle the left sidebar.
  - `Ctrl+Shift+F` / `Cmd+Shift+F`: Open sidebar and focus session title search.
  - `Ctrl+K` / `Cmd+K`: Open the model picker menu in the composer.
  - `Shift+Tab`: Cycle thinking levels for the Main model in the composer.
  - `Ctrl+J` / `Cmd+J`: Toggle the right panel on the **Side chat** tab and focus its input.
  - `Esc` (or Android Back): Close open menus/dialogs; in a session, offer to dismiss an open question, discard an open practice problem, or abort a running turn.

## right-panel-and-side-chat

The right panel in a session contains four tabs (**Plan**, **Jobs**, **Side chat**, and **Activity**):
- **Plan**: Shows the live lesson dependency graph (`plan_init`) in Teaching sessions, highlighting visited and current nodes. Supports zoom, pan, and fit.
- **Jobs**: Lists running and completed background jobs (`research`, `pdf`, `demo`, `visual`) and active graph extractions for the session, with elapsed time, cost label, and an **End** button to abort a running job.
- **Side chat**: Lets the learner ask clarification questions anchored to any teaching segment or text selection (select assistant text → click **Ask**, up to 4,000 characters) without derailing the main thread. A separate helper answers using the foreground model (with open question answer keys and open problem solutions hidden), and new exchanges are delivered to the main agent on its next turn as hidden context updates.
- **Activity**: Activity tab in the right panel (currently a placeholder showing `Nothing yet`).
- **Stats bar**: Shown beneath the composer or dock (`41k / 200k · CLI`). Clicking it opens **Session stats** with last-call context tokens, cache hit rate, subscription/usage totals, and a per-turn breakdown.

## knowledge-graph

Open the knowledge graph from **Knowledge graph** in the left sidebar (`/graph`):
- **Extraction**: Teaching sessions automatically extract propositions and logical implication chains (`premises ⟹ conclusion`) onto the graph once uncovered teacher prose reaches the chunk threshold, using the **Cheap** model slot for the Extractor and Auditor stages. Practice and Chat sessions never run graph extraction. You can also trigger extraction manually from the header coverage ring (**Extract now**) or import markdown/text/PDF notes via **Extract files…**.
- **Canvas & folder filter**: Drag nodes with live physics, search nodes, adjust display/physics sliders under the gear menu, or filter visible clusters by folder using the top-left funnel button (**Show folders**).
- **Chains table & picks**: Click **Chains** on `/graph` (or **Pick nodes** on `/session/new`) to browse propositions grouped by source and folder, reorganize sources, delete nodes/sources, or pick propositions to seed a new Teaching or Practice session with a **Graph context** card.

## settings-appearance

**Settings → Appearance** (`/settings?section=appearance`):
- **Theme**: Choose **Dark**, **Light**, or **System**.
- **Transcript width**: Desktop slider from `46rem` to `120rem` (in `2rem` steps) or **Full** (default) to cap the reading width of session transcripts.

## settings-models

**Settings → Models** (`/settings?section=models`):
- Configures the three required global model slots:
  - **Main (`strong`)**: Used by Prober, Teacher, Practitioner, Chat agent, and Side chat helper. Overridable per session via the composer model pill (`Ctrl+K`).
  - **Cheap (`cheap`)**: Used by background workers (Researcher, Demo builder, Graph Extractor, Graph Auditor, and automatic session Title generator).
  - **Vision (`vision`)**: Must support image input; used by Visual maker and PDF reader workers.
- Each slot picks an account, model, and optional thinking level (`minimal`, `low`, `medium`, `high`, `xhigh`, `max`). Click **Refresh model lists** to force a catalog refresh across accounts.

## settings-accounts

**Settings → Accounts** (`/settings?section=accounts`):
- **Claude Code**: Uses the locally installed `claude` CLI subscription (`opus`, `sonnet`, `haiku`). Shows installation state, binary path, version, and an **Allow background use** toggle (controls whether automatic extraction, compaction, and background jobs may use Claude Code).
- **ChatGPT**: Connects one or more ChatGPT Plus/Pro/Team accounts via OAuth sign-in. Supports **Add account**, **Sign in again**, **Remove**, and an **Allow background use** toggle.
- On a remote/mobile client, Accounts is read-only and managed from the laptop under **Settings → Sync**.

## settings-lesson

**Settings → Lesson** (`/settings?section=lesson`):
- **Quizzing**: Choose **Multiple choice** (`probe` / `quiz` with options and confidence slider) or **Free recall** (`recall` / `explain` where the learner types an open explanation graded against the agent's committed answer).
- **Compaction limit**: Token threshold at which older session history is summarized into a compaction checkpoint (default `150,000`, minimum `32,000`).
- **File access** (desktop/local only): Controls learner-file tools (`read`, `ls`, `find`, `grep`), `pdf` jobs, and `show_image`. By default file access is unrestricted: relative paths (and `~/...`) resolve against the learner's home directory, an omitted `path` defaults to home, and absolute paths outside home are permitted, subject to protected-path checks that always block sensitive locations (such as `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.claude`, browser profiles, Verstehen/LearnHarness credential files, and `.env` / `.env.*` files). Enabling **Restrict to listed folders** limits access to the explicitly listed allowed folder subtrees (still enforcing protected-path denials); in restricted mode, omitting `path` lists the allowed roots in `ls` and searches across them in `find` and `grep`.

## settings-prompts

**Settings → Prompts** (`/settings?section=prompts`):
- Lists prompt fragments for **Teacher**, **Prober**, **Practice**, **Chat**, and **Shared** (showing which agents share each fragment).
- **View default** inspects the shipped markdown. **+ Add override** / **Edit override** saves a custom override file under `<data_dir>/prompts/` and activates its switch in `agent.prompts`. Each row's switch toggles between the override and the shipped default without deleting the file; **Delete override** removes the file and turns the switch off.

## settings-graph

**Settings → Graph** (`/settings?section=graph`):
- **Extraction**: Master toggle (`graph.enabled`) for automatic and manual knowledge-graph extraction.
- **Graph rendering**: Toggles the interactive 2D force-directed canvas on `/graph` (`graph.rendering`); when off, `/graph` shows the summary view and Chains table button.
- **Extraction chunk budget**: Uncovered token threshold (`graph.extraction_chunk_tokens`, default `4096`, minimum `500`) before automatic background extraction triggers at turn settlement.
- **Graph tools**: Toggles (`agent.graph_tools`) whether the Prober and Practitioner receive `list_sessions` and `list_propositions` to inspect the knowledge graph's structure (requires Extraction on). The Chat agent always has its own read-only graph inspection tools (`list_graph_nodes`, `read_graph_node`).

## settings-tools

**Settings → Tools** (`/settings?section=tools`):
- **Background tools**: Four switches (`tools.research`, `tools.demo`, `tools.visual`, `tools.pdf`) controlling which background sub-agent tools are armed. (Prober and Chat agents only use `research` and `pdf`; Practitioner always arms `research` and `pdf`; Teacher uses all enabled tools.)
- **Concurrent worker requests**: Caps parallel model requests across background workers and extraction (`worker_request_concurrency`, empty = default `8`).
- **Research search engine**: Choose **Native** (ChatGPT native web search when Cheap slot is ChatGPT), **Tavily**, or **Brave**, and configure masked Tavily/Brave API keys (or read-only `TAVILY_API_KEY` / `BRAVE_API_KEY` environment keys) with automatic fallback order displayed.
- **Demo browser** (server/non-desktop mode): Configures or downloads the headless Chromium executable used to verify interactive HTML demos. (On desktop, QtWebEngine verifies demos directly.)

## settings-plugins

**Settings → Plugins** (`/settings?section=plugins`, desktop only):
- Discovers plugins placed in `<data_dir>/plugins/<id>/dist/`. Shows each plugin's name, version, status (`disabled`, `activating`, `active`, `invalid`, `failed`), warnings/errors, an enable switch, and a **Settings** button for plugin-contributed settings.
- Active plugins can contribute custom views, sidebar/graph/session top-bar actions, and agent tools/instructions for `prober`, `teacher`, and `practice` turns.

## settings-sync-and-connection

- **Settings → Sync** (`/settings?section=sync`, laptop/desktop): Installs or updates a remote `verstehen --server` over SSH (with TOFU `known_hosts` verification), pairs with an existing server, manages the server's ChatGPT accounts via an SSH tunnel and views server Claude Code status, generates 8-character pairing codes for the Android app, and revokes paired devices or disconnects.
- **Settings → Connection** (`/settings?section=connection`, remote/Android client): Shows the paired Tailscale server address (`100.x.y.z:port`), device name, and a **Disconnect** button to revoke the device token and return to `/pair`.
