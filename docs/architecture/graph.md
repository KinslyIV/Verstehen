# Knowledge graph

Owns the knowledge graph: propositions, chains, coverage of what was taught, sources (sessions
and imported notes), the extraction pipeline that grows the graph, and the graph page.

LearnHarness spec: [knowledge graph and imports](../learnharness/knowledge-graph.md).

## Code map

Backend, `backend/src/verstehen/graph/`:

| File | What it holds |
|---|---|
| `extraction_service.py` | `ExtractionService`: app-wide source runs (one per source), serial batches per source, the FIFO audit and merge gate, notes imports, abort, `deleting_source` wind-down context |
| `extractor.py`, `auditor.py`, `prompts.py` | the extractor and auditor agents with LH's prompts and tool texts; findings are healed and validated against the canonical `merge.py` models |
| `candidates.py` | BM25 candidate pages for the auditor |
| `merge.py` | the canonical findings and audit-verdict models, deterministic merge, and chain simplification, committed with coverage or a notes checkpoint in one transaction |
| `coverage.py` | which teacher prose is covered, fingerprints, batching |
| `service.py` | `GraphService`: snapshot, node deletion, positions, render settings, source organization and deletion, costs |
| `model.py`, `snapshot.py` | read-time merging (identity, aliases, chains), derived edges and implications, birth-session clusters, session index and birth-session formatters (`format_graph_sessions`, `format_graph_propositions`) |
| `organization.py`, `deletion.py`, `positions.py` | folders and moves, deletion modes, position sanitization |
| `notes.py`, `pdf_markdown.py` | notes files and PDF-to-Markdown on PDFium |
| `context.py` | the `graph-context` marker for a session started from picks |
| `render_settings.py`, `costs.py`, `errors.py` | render settings sanitizer, cost summary, `GraphRefused` |

Frontend, `app/src/lib/graph/` and the `/graph` route:

| File | What it holds |
|---|---|
| `graph-page.svelte`, `controller.svelte.ts` | the page and its data: the snapshot and render settings load together, costs and status after the first paint; `graph-changed` refetches the snapshot and costs unless the page's own position save made it; `sessions-changed` retitles clusters from `GET /api/graph/titles`; `extractions-changed` refreshes the extraction status |
| `canvas.ts`, `graph-canvas.svelte` | the TypeScript port of LH's Canvas 2D renderer with a d3-zoom camera; the live d3-force simulation is built on the first node press or physics change, and `pickNode` hit-tests without allocating |
| `layout.ts`, `layout-settle.ts` | the d3-force layout and the page-side settle |
| `chain-table*.ts/.svelte`, `source-*.svelte`, `source-*.ts`, `tree-*.ts` | the chains table, folders, drag moves (`source-drop.svelte.ts`, shared with the sidebar), the sidebar tree builder in `source-organization.ts`, keyboard navigation |
| `picks*.ts`, `node-picker.svelte` | the shared pick selection for starting a session |
| `delete-*-dialog.svelte` | node, source, and session-trace deletion |
| `coverage-ring.svelte`, `coverage-menu-block.svelte`, `extract-now-button.svelte` | coverage in the lesson header and session menu |
| `render-settings*.ts/.svelte`, `cost-control.svelte`, `pipeline-pills.svelte`, `import-notes.svelte` | settings panel, cost pill, running extractions, notes import |

## How it works

- **Extraction.** When a turn settles, `ExtractionService.trigger` runs if extraction is on, enough
  teacher prose is uncovered (`graph.extraction_chunk_tokens`, default 4,096), and background
  consent allows it. **Extract now** and notes imports are foreground.
- **Pipeline.** For each batch: the extractor proposes propositions and chains; the auditor reviews
  them against BM25 candidates; the merge applies the verdicts deterministically and commits with
  the coverage or checkpoint. Audit and merge are serialized app-wide (FIFO).
- **Stored as ledgers, merged on read.** A node's first row is its identity; later assertions are
  link rows. `GET /api/graph` merges identities, aliases, and chains at read time, as LH does.
- **The page settles the layout.** The server only stores positions. When nodes lack one and
  Graph rendering is on, the page runs the settle and saves it with `PUT /api/graph/positions`.
- **Position saves return their revision.** The page skips the refetch for revisions created
  by its own saves. A save that changes nothing returns a null revision. A snapshot older
  than the position save retains the saved positions.
- **Loading order.** The snapshot (with the teaching and practice session counts the summary
  needs), the Graph settings and the render settings are requested together; costs and extraction
  status are requested only after the graph has arrived. Costs title their sources from sessions
  and notes sources without reading the whole ledger.
- **Picks.** One selection is shared by the new-session screen and the graph page. Sending adds the
  `graph-context` marker, projected to the model before the learner's first message.
- **Deletion modes.** Deleting a session uses `preserve-graph` or `delete-nodes` (remove what only
  this session added). Deletion waits up to ten seconds for the session's extraction to wind down.
- **Prober graph tools** (`list_sessions`, `list_propositions`) exist only while extraction and
  `agent.graph_tools` are both on; the practitioner gets the same two tools under the same gate.
- **Practice sessions never extract.** `POST /api/graph/coverage/extract` refuses them with 400,
  their detail has `coverage = null`, and the UI hides the coverage ring and the session menu's
  coverage block. Picks started in practice mode add the same `graph-context` marker, shown as the
  collapsed Graph context card. The chains table leaves out sources whose `session_kind` is
  `practice`, and the summary view counts practice sessions on their own row.

## Data and events

- Tables: `graph_nodes`, `graph_node_links`, `graph_chains`, `graph_coverage`,
  `graph_checkpoints`, `graph_sources`, `graph_source_folders`, `graph_source_placements`,
  `graph_positions`, `graph_revision`; extractor and auditor rows in `usage` ([store](store.md)).
- Reads for the page: `GET /api/graph` (snapshot, with `teach_sessions` and `practice_sessions`),
  `GET /api/graph/titles` (every session's title, for retitling), `GET /api/graph/costs`,
  `GET /api/graph/status`; `PUT /api/graph/positions` answers with its revision.
- Notifications: `graph-changed` (with the new revision, after a commit that changed the
  ledgers; a no-op transaction sends nothing) and `extractions-changed`.
- Settings: `graph.enabled`, `graph.rendering`, `graph.extraction_chunk_tokens`,
  `agent.graph_tools`; render settings under the `graph_render_settings` settings key.

## Collaborators

- `SessionService`, `TurnService`, and `GraphService` receive `ExtractionService` through their
  constructors (`TurnService` reads the graph directly from `GraphStore` and `SessionsStore` for
  prober graph tools). Extraction admits requests through the jobs' `WorkerAdmission`
  ([jobs](jobs.md)). `GraphService` deletes sessions through an injected function.

## Traps found in M1–M9

- **Coverage counts only teacher prose and delivered `send_to_user` text** (`teaching/prose.py`),
  the same selection side chat uses.
- **PDFium is not thread-safe.** PDF workers and notes imports share `teaching/pdfium.py`'s lock.
  PDF Markdown can differ slightly from LH's pdfjs output, including column order.
- **The `usage` table has no session foreign key** (notes sources use `src_…` ids); a trigger
  removes a deleted session's rows.
- **A click right after a drag is ignored while the simulation settles**, and a camera move closes
  the detail card, including the tail of a wheel zoom. Both are LH's behavior
  (`onPointerUp` treats a press while the simulation is active as a drag; `onCameraMove` clears the
  card). On a 3,000-node graph the settle lasts well over ten seconds, so clicks seem erratic.
  Changing either needs a decision.
- **A drag commit is expensive on the server**: every node's position is rewritten and synced
  (3,000 nodes take about three seconds), then the layout is saved once the settle ends.
- **Trackpad pinch inside the desktop app (WebKitGTK) bypasses the page**: GTK delivers it to
  WebKit's native magnification, which scales the whole page and never reaches `wheel` handlers.
  Only Chromium behavior is covered by the flows.
- **Not ported yet:** the activity dock (M11), plugin knowledge picker.
