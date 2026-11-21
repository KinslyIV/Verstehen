# Knowledge graph

Owns the knowledge graph: propositions, chains, coverage of what was taught, sources (sessions
and imported notes), the extraction pipeline that grows the graph, and the graph page.

LearnHarness spec: [knowledge graph and imports](../learnharness/knowledge-graph.md).

## Code map

Backend, `backend/src/verstehen/graph/`:

| File | What it holds |
|---|---|
| `extraction_service.py` | `ExtractionService`: app-wide source runs (one per source), serial batches per source, the FIFO audit and merge gate, notes imports, abort, deletion wind-down |
| `extractor.py`, `auditor.py`, `prompts.py` | the extractor and auditor agents with LH's prompts and tool texts; findings are healed and validated |
| `candidates.py` | BM25 candidate pages for the auditor |
| `merge.py` | the deterministic merge and chain simplification, committed with coverage or a notes checkpoint in one transaction |
| `coverage.py` | which teacher prose is covered, fingerprints, batching |
| `service.py` | `GraphService`: snapshot, node deletion, positions, render settings, source organization and deletion, costs |
| `model.py`, `snapshot.py` | read-time merging (identity, aliases, chains), derived edges and implications, birth-session clusters, the session readers |
| `organization.py`, `deletion.py`, `positions.py` | folders and moves, deletion modes, position sanitization |
| `notes.py`, `pdf_markdown.py` | notes files and PDF-to-Markdown on PDFium |
| `context.py` | the `graph-context` marker for a session started from picks |
| `render_settings.py`, `costs.py`, `errors.py` | render settings sanitizer, cost summary, `GraphRefused` |

Frontend, `app/src/lib/graph/` and the `/graph` route:

| File | What it holds |
|---|---|
| `graph-page.svelte`, `controller.svelte.ts` | the page and its snapshot: `graph-changed` refetches the snapshot and costs, `extractions-changed` refreshes the extraction status |
| `canvas.ts`, `graph-canvas.svelte` | the TypeScript port of LH's Canvas 2D renderer with a d3-zoom camera |
| `layout.ts`, `layout-settle.ts` | the d3-force layout and the page-side settle |
| `chain-table*.ts/.svelte`, `source-*.svelte`, `tree-*.ts` | the chains table, folders, drag moves, keyboard navigation |
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
- **Picks.** One selection is shared by the new-session screen and the graph page. Sending adds the
  `graph-context` marker, projected to the model before the learner's first message.
- **Deletion modes.** Deleting a session uses `preserve-graph` or `delete-nodes` (remove what only
  this session added). Deletion waits up to ten seconds for the session's extraction to wind down.
- **Prober graph tools** (`list_sessions`, `list_propositions`) exist only while extraction and
  `agent.graph_tools` are both on.

## Data and events

- Tables: `graph_nodes`, `graph_node_links`, `graph_chains`, `graph_coverage`,
  `graph_checkpoints`, `graph_sources`, `graph_source_folders`, `graph_source_placements`,
  `graph_positions`, `graph_revision`; extractor and auditor rows in `usage` ([store](store.md)).
- Notifications: `graph-changed` (with the new revision, after a commit that changed the
  ledgers; a no-op transaction sends nothing) and `extractions-changed`.
- Settings: `graph.enabled`, `graph.rendering`, `graph.extraction_chunk_tokens`,
  `agent.graph_tools`; render settings under the `graph_render_settings` settings key.

## Collaborators

- `SessionService`, `TurnService`, and `GraphService` receive `ExtractionService` through their
  constructors. Extraction admits requests through the jobs' `WorkerAdmission`
  ([jobs](jobs.md)). `GraphService` deletes sessions through an injected function.

## Traps found in M1–M9

- **Coverage counts only teacher prose and delivered `send_to_user` text** (`teaching/prose.py`),
  the same selection side chat uses.
- **PDFium is not thread-safe.** PDF workers and notes imports share `teaching/pdfium.py`'s lock.
  PDF Markdown can differ slightly from LH's pdfjs output, including column order.
- **The `usage` table has no session foreign key** (notes sources use `src_…` ids); a trigger
  removes a deleted session's rows.
- **Not ported yet:** practice graph tools (M10), the activity dock (M11), plugin knowledge picker.
