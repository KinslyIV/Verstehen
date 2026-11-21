# M9 plan: knowledge graph

> Status: **approved by the user, 2026-11-20.** Decisions are in [decisions](../decisions.md).
> LearnHarness references are at commit `cb25c8e` (checkout: `/home/immata/learnharness`). Spec:
> [knowledge graph](../learnharness/knowledge-graph.md). Where a doc and the LH code disagree, the
> code is right.

**Done when:** after enough teaching, a session's teacher prose is extracted in the background
into propositions and reasoning chains. An auditor links them to existing ideas, and a
deterministic merge writes them in one transaction with their coverage. Notes files (text,
Markdown, PDF) can be imported through the same pipeline. The **Knowledge graph** page draws the
graph on LH's canvas with clusters, search, a detail card, render settings, costs, and running
pipeline pills. The chains table lists every chain by source, organizes sources into folders, picks
propositions for a new session, and deletes nodes and sources. A session shows its coverage ring
with Extract now, and its Jobs tab lists its extractions. The prober can read the graph.
`make check`, `make verify`, and `make verify-live` pass; the feature map and status are updated.

## User decisions for M9

1. **The canvas is a port of LH's own renderer.** `components/graph-canvas.ts` (one Canvas 2D, one
   requestAnimationFrame loop with a dirty flag, d3-zoom camera, nearest-node picking) and
   `src/core/layout.ts` (d3-force) are ported to TypeScript. This replaces "Svelte Flow, d3-force,
   dagre" in the roadmap and the architecture: LH imports no `@xyflow`, and Svelte Flow is a DOM
   node editor without hulls, label fading, or canvas picking.
2. **The graph has its own page.** A **Knowledge graph** entry in the sidebar opens `/graph`. `/` and
   `/session/new` keep the plain new-session screen. (LH makes the graph its home.)
3. **Picks on both screens, one selection.** The new-session screen always shows LH's chip ("Pick
   nodes" / "N nodes selected" with Clear), which opens the chains table in pick mode. The graph
   page shows **Start session** once something is picked; it opens the new-session screen with the
   picks kept. Sending starts the session with LH's `graph-context` marker.
4. **Everything in LH's graph surface is in M9:** node and source deletion (and the session delete
   dialog's "Also remove its graph traces" checkbox), source organization (folders, rename, drag),
   the full render settings panel, the cost pill, and the graph settings (extraction on/off,
   rendering on/off, chunk tokens, prober graph tools).
5. **The graph page settles the layout.** The server only stores positions. When the snapshot has
   nodes without a position, the page runs the TypeScript port of LH's settle
   (`src/core/layout-settle.ts`, `incrementalLayout`) and saves it with `PUT /api/graph/positions`.
   The layout is the same (deterministic seeds); new nodes are placed when the graph is next
   opened instead of at merge time. LH settles on the server after every merge
   (`extraction.ts:1195`, `:1362`) and after a drag commit (`src/server/commit-positions.ts:67`).

## Proposed by the orchestrator (your OK with the plan)

- **Settings → Graph** is a new settings section holding LH's four switches: Extraction (LH
  `graph.enabled`, default on), Graph rendering (`graph.rendering`, default on), Extraction chunk
  size (`graph.extractionChunkTokens`, default 4,096, floored at 500, the compaction-limit field's
  commit behavior), and Prober graph tools (`agent.graphTools`, default on; effective only with
  Extraction on, LH `graphToolsEnabled` `settings-resolution.ts:284`).
- **The right panel is hidden on `/graph`.** Its tabs are all about the open session. Running
  extractions for any source show as the graph page's pipeline pills, as in LH.
- **PDF import uses PDFium.** LH's rules (`src/agent/subagents/pdf-markdown.ts`: headings from font
  size, line breaks, lists, image-only and empty pages) are ported onto pypdfium2's per-character
  text, boxes, and font sizes, which M7 already ships. The Markdown can differ slightly from pdfjs.
- **Storage** follows the architecture tables (`graph_nodes`, `graph_node_links`, `graph_chains`,
  `graph_coverage`, `graph_checkpoints`, `graph_sources`, `graph_source_folders`,
  `graph_positions`); render settings are one `settings` key. A node's first row is its identity,
  and later assertions are link rows. Read-time merging stays as in LH (`getGraph`, `graph.ts:406`).
- **One event, `graph-changed`,** on `/api/events` carries a graph revision number. It is sent after
  every merge, deletion, organization change, or positions write; extraction start, phase, and
  finish send `extractions-changed`. LH's `lh:graph-revision` and status polling become these.
- **Usage:** each extractor and auditor call writes a `usage` row with role `extractor` or
  `auditor` and its source id (session or `src_…`). The cost pill and the Jobs rows read them.

## Flagged

- **The render settings panel has about 18 sliders, not 5.** I said five while asking. LH's gear
  opens Display (node size, edge width, arrowhead size, label size, labels until zoom, cluster
  labels), Regions (on/off, dilation, blur, edge alpha, cluster label size), Physics (node
  repulsion, edge attraction, edge length, central pull, cluster pull, friction), and Depth
  (strength, spacing, base ring radius) (`components/graph-view.tsx:435-790`,
  `src/core/render-settings.ts`). All of it is ported (decision 4).
- **The canvas has live physics while dragging a node** (`graph-canvas.ts:1112-1147`). With
  decision 5 the same TypeScript simulation drives both drag and settle.
- **LH's header comments have drifted** (`contracts/graph.ts:157-190` still mentions supports
  edges and bridging). The port follows the types and code (chains only, identity links only).
- **Extraction is background work.** It goes through `ProviderPolicy.admit("background")`, so a
  provider with background consent off skips automatic extraction. Manual Extract now and imports
  are foreground (`chat-handler.ts:132-148`; LH treats the routes as user-started).

## Not in M9

| Left out | Comes with |
|---|---|
| Practice graph tools and problem targets (`chat-handler.ts:745`) | M10 |
| The activity dock (app-wide) | M11 |
| Plugin knowledge picker (`components/plugin-knowledge-picker.tsx`) | not ported (plugins deferred) |
| Embeddings, clustering, and labeling rungs | not in LH's current code (removed in wave 7) |

## Tasks

T1, then T2, then T3, then T4, on `m9-plan` in its worktree, each reviewed before the next starts.
T1–T2 are backend; T3–T4 are UI.

### T1. Graph store, snapshot, merge, deletion (backend)

- **Migration `0006_graph.sql`** and `store/graph.py` (`GraphStore`): the tables above, all writes in
  `transaction()`. Ids `n_…`, `arg_…`, `src_…` as in LH.
- **Read model** (`graph/model.py`, LH `getGraph` `graph.ts:406`, `deriveView` `:457`): merge node
  rows and link rows (aliases, provenance union), merge chains by `(premises, conclusion)`, derive
  edges and implication nodes.
- **Snapshot** (`graph/snapshot.py`, LH `graphSnapshot` `:510-636`): edges, implication nodes,
  clusters by birth session (`session-clusters.ts:50-130`, hulls from 3 members), positions,
  `nodeSessions` with LH's source lookup (live session wins, last duplicate wins, missing ones
  left out, `:531-556`), revision.
- **Merge** (`graph/merge.py`, LH `mergeFindings` `:149`, `simplifyChains` `:301`): resolve links
  to link rows, mint new nodes, map chain endpoints, simplify redundant chains, and write coverage or
  the notes checkpoint, all in one transaction (architecture decision).
- **Candidates** (`graph/candidates.py`, LH `proposition-candidates.ts:35-169`): BM25 (k1 1.2,
  b 0.75), name + statement and name + alias scored separately, English stop words, pages of 5,
  hint words.
- **Session readers** (LH `graphSessionIndex` `:638`, `graphSessionPropositions` `:688`).
- **Deletion** (`graph/deletion.py`, LH `graph-deletion.ts:95-343`): session traces in
  `preserve-graph` and `delete-nodes` modes, sources, and single nodes. Surviving nodes keep their
  identity row; orphans and their positions go; chains die when their provenance empties or a
  member dies.
- **Source organization** (`graph/organization.py`, LH `source-organization.ts:38-159`): folders,
  placements, display names, LH's action parser and move rules, imported-source placement.
- **Render settings** (LH `render-settings.ts:79-394`): sanitizer and defaults, stored as one key.
- **Costs** (LH `cost-summary.ts:124`): totals and per-source breakdown from `usage`, with
  `planCostLabel` for subscriptions.
- **Routes** (`api/graph.py`): `GET /api/graph` (snapshot), `DELETE /api/graph/nodes/{id}`,
  `GET|POST|DELETE /api/graph/sources` (list, organization action, delete with mode),
  `PUT /api/graph/positions` (known ids only, sanitized, LH `commit-positions.ts`),
  `GET|PUT /api/graph/render-settings`, `GET /api/graph/costs`. LH's error texts and status codes.
  `graph-changed` event. Regenerate API types.
- **Tests:** read-time merge (first row defines identity, later rows become aliases); chain merge
  and simplification; edge and implication derivation; clusters by birth session; the source
  lookup rules; merge writes coverage in the same transaction and a failure writes nothing; BM25
  ranking and paging with hints; each deletion mode keeps shared knowledge; organization moves
  refuse cycles; positions drop unknown ids; render settings sanitize; cost totals.

### T2. Extraction pipeline, imports, and teaching hooks (backend, on T1)

- **Coverage** (`graph/coverage.py`, LH `coverage.ts:38-192`): teacher prose view lines (including
  delivered `send_to_user`), SHA-256 fingerprints, `coverageOf`, `batchRuns` (oldest first, never
  splitting a message), `batchTag`. Exposed as `coverage` in the session detail (LH
  `SessionCoverage`).
- **Extractor** (`graph/extractor.py`, LH `extraction.ts:387-558`): `EXTRACTION_CORE`, the session
  and notes preambles, `EXTRACTOR_INSTRUCTIONS`, `NOTES_EXTRACTOR_INSTRUCTIONS`, and
  `sourceDigest` ("THE GRAPH SO FAR") **verbatim**. One `submit_findings` output tool with LH's
  schema descriptions, healing (`fillFindings`, stringified arrays), and validation
  (`validateFindingsChains`, `validateSessionAnchors` `:312-364`) returned as retry messages.
  Model: `resolve("extractor")`.
- **Auditor** (`graph/auditor.py`, LH `AUDITOR_INSTRUCTIONS` `:559`, `runAuditor` `:587`, tools
  `src/agent/tools/graph.ts:118-209`): findings plus about 5 candidates each
  (`prepareAuditorReview`), `find_candidates`, `list_sessions`, `list_propositions`,
  `submit_review { links }`, at most 16 turns, verbatim texts. Model: `resolve("auditor")`.
- **`ExtractionService`** (`graph/service.py`, LH `createExtractionPipeline` `:797-1430`): app-wide.
  Single flight per source, batches of one source serial, one FIFO audit lock around audit and
  merge, per-chunk jobs, abort by source, status for running runs (phase extracting, auditing,
  merging), LH's refusal when no model is configured, and usage rows. Started from the turn
  settle as follow-up work (architecture step 11) when Extraction is on, the session is not
  practice, and uncovered tokens reach the chunk size (LH `triggerExtraction`,
  `turn-service.ts:109`).
- **Notes import** (`graph/notes.py`, LH `app/api/graph/import/route.ts`, `lib/notes-import-limits.ts`):
  `POST /api/graph/import` multipart, 25 MiB total, LH's extension allowlist and binary heuristic
  (first 8 KiB), at most 1,000 PDF pages, source id `src_` + hash of the path, whole file each
  time, notes prompts, checkpoint, organization placement.
- **PDF to Markdown** (`graph/pdf_markdown.py`): proposal above.
- **Routes:** `POST /api/graph/coverage/extract` (409 while running, LH text),
  `GET /api/graph/status`, `POST /api/graph/extractions/{source}/abort`, the import route.
  `extractions-changed` event.
- **Teaching hooks:**
  - prober graph tools `list_sessions` and `list_propositions` (LH `proberGraphTools`
    `tools/graph.ts:43-117`) when the gate is open;
  - session create accepts `graph_context` picks and writes LH's `graph-context` marker
    (`newGraphContextMessage`, `native-messages.ts:322`) as the first entry, text verbatim;
  - session delete takes `mode=preserve-graph|delete-nodes` (LH `app/api/chats/[id]/route.ts:70-90`):
    409 while a turn or job runs, 503 while its extraction winds down, LH's texts.
- **Settings:** the four graph settings (proposal above), sanitized as LH (`settings.ts:425-560`,
  `:810-835`).
- **Fake model:** extractor and auditor run with script roles `extractor` and `auditor`.
- **Tests:** only teacher prose counts toward coverage; a changed message is uncovered again;
  batching never splits a message; the trigger fires at the chunk size and not below, and never
  for practice or with Extraction off; extractor validation rejects unknown chain endpoints with
  LH's text and heals stringified arrays; the auditor sees findings and candidates but no source;
  linked findings become aliases; a failure leaves the batch uncovered; two sources audit one at
  a time; abort stops a run; import refuses binary, oversized, and disallowed files; re-import
  reuses the source id; a PDF becomes headed Markdown; prober tools appear only with the gate
  open; the graph-context marker text; both delete modes and their refusals.

### T3. Graph page (UI, on T2)

Behavior from LH `components/graph-view.tsx` and `graph-canvas.ts`; the look is ours.

- **Route `/graph`** in the lesson layout, sidebar entry **Knowledge graph** (decision 2), right
  panel hidden (proposal).
- **Canvas** (`app/src/lib/graph/canvas.ts`, port of `graph-canvas.ts`): hull fills and strokes,
  edges and arrowheads, nodes, region labels, node labels with LH's zoom gate and fade
  (`LABELS_FADE_RATIO`), hover glow over about 180 ms, picking pad, d3-zoom camera that data
  refetches never move, node drag with live physics, theme colors resolved from our tokens,
  cluster hue from the cluster id (`cluster-geometry.ts`). Pure helpers keep LH's unit tests
  (`tests/graph-canvas.test.ts`).
- **Layout** (`app/src/lib/graph/layout.ts`, port of `layout.ts` and `layout-settle.ts`):
  decision 5.
- **Chrome** (LH `graph-view.tsx`): search box (hides nodes, edges, and labels; closes a filtered
  card), settings gear with the full panel (flagged), cost pill with its breakdown popover
  (`GraphCostControl` `:299-430`), running pipeline pills under it, Import notes control with LH's
  queue (three at a time, folder picks skip hidden files, LH's summaries, `notes-import.tsx`,
  `notes-import-queue.ts`), the chains table button, and Start session (decision 3).
- **Detail card** (`:900-945`, `:1461-1468`, `:1620-1665`): name and statement as static Markdown and
  math, the Sessions list (links, plain text for notes, "No sessions recorded."), placement below
  the node, flipped near the bottom, clamped; any camera move or an empty-stage click closes it;
  Delete opens the node dialog (T4).
- **Empty graph** and **rendering off** (LH `minimal-home.tsx`): the summary view with the same
  chrome in the same places.
- **Refresh** on `graph-changed`, `extractions-changed`, and resync.
- **Tests (Vitest):** canvas helpers (label gate, picking, hull geometry); layout determinism and
  incremental placement; search filtering; card placement; render settings ladders.

### T4. Chains table, deletion, picks, and session surfaces (UI, on T3)

- **Chains table overlay** (LH `chain-table.tsx`, `chain-navigation.ts`, `tree-presentation.tsx`,
  `source-folder-tree.tsx`): source → chain → statements, everything collapsed at first; chain
  lines as chips joined with KaTeX ∧ and ⟹; sort by Name, Props, Created; fuzzy search over
  names, aliases, and statements (`fuzzy.ts`); LH's keyboard navigation; the floating selection
  bar with `chainsForSelection` (`chains.ts:34`), Clear, and Delete; folders with create, rename,
  drag, and move rules; source rename. Opened from the graph page and, in pick mode, from the
  new-session chip.
- **Picks** (decision 3): one shared selection in the app, the chip and Clear on the new-session
  screen (LH `NodePickerControl`, `composer-actions.tsx:23-61`), Start session on the graph page,
  `graph_context` sent with the new session.
- **Delete dialogs:** node (LH `delete-node-dialog.tsx`, with the unioned impact for several),
  source (`delete-source-dialog.tsx`), and the session delete dialog's "Also remove its graph
  traces" checkbox (`delete-session-dialog.tsx`, `TRACES_COPY` verbatim; Try again on 409 and 503).
- **Coverage ring** (LH `extraction-coverage.tsx`): in the lesson header, filling with uncovered
  tokens over the chunk size, pulsing while a run is in flight, hidden with Extraction off; its
  popover and the session row's context menu block show LH's coverage numbers and **Extract now**
  (409 is benign).
- **Jobs tab extraction rows** (M7 decision; LH `activity-dock.tsx:274-282`, `:425-428`):
  "Extraction — {phase}" with elapsed time and End (abort by source).
- **Settings → Graph** (proposal).
- **Tests (Vitest):** chain line formatting; selection to chains; sort and search; folder moves;
  pick chip states; coverage ring fill; delete dialog copy and retry.

## Verify flows (fake model)

| Flow | Task | Shows |
|---|---|---|
| `graph-extraction` | T3 | a lesson passes the chunk size → extraction runs → graph page shows the new nodes and a cluster |
| `graph-canvas` (dark/light) | T3 | seeded graph: hulls, labels at zoom, hover, detail card with Sessions |
| `graph-search-settings` | T3 | search hides nodes; render settings change the drawing and survive reload |
| `graph-import` | T3 | import a Markdown file and a PDF → pills → nodes under the notes source |
| `graph-rendering-off` | T3 | Settings → Graph rendering off → summary view with the chains table |
| `graph-chains-table` | T4 | expand source → chain → statements, sort, search, organize folders |
| `graph-picks` | T4 | pick on the graph page → Start session → chip shows the count → the session starts with the hidden marker; pick from the new-session chip |
| `graph-delete` | T4 | delete a node from the card and a source from the table; delete a session with traces |
| `graph-coverage` | T4 | the ring fills, Extract now runs, the Jobs tab shows the extraction row and End |
| `settings-graph` | T4 | the four settings save and reload |

`make verify-live` stays as it is.

## Feature map entries

Knowledge graph page; canvas and detail card; search and render settings; cost and pipeline
pills; notes import; chains table and source folders; picks and graph context; node, source, and
session-trace deletion; coverage ring and Extract now; Jobs-tab extractions; Settings → Graph;
prober graph tools.

## Open questions

None, unless the proposals above are rejected.
