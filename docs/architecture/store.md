# Storage

Owns all SQL: the one SQLite connection, migrations, and one store module per entity. Nothing
outside `store/` imports `sqlite3` or `aiosqlite` (ruff banned-API), and nothing in `store/`
imports Pydantic AI.

LearnHarness spec: [storage and events](../learnharness/storage-and-events.md).

## Code map

`backend/src/verstehen/store/`:

| File | What it holds |
|---|---|
| `database.py` | `Database`: one aiosqlite connection (WAL, foreign keys) behind one asyncio lock; `transaction()` (BEGIN, commit, rollback on any exception) and `read()` |
| `migrate.py`, `migration_files.py`, `migrations/*.sql`, `migrations.lock` | the migration runner; numbered `NNNN_name.sql` files; SHA-256 lock entries that `make check` verifies |
| `entries.py` | the entry models (`UserEntry`, `AssistantEntry`, `ToolResultEntry`, `MarkerEntry`) and `EntriesStore` (append-only; `append_compaction` saves a checkpoint with its usage) |
| `sessions.py` | `Session` and `SessionsStore` (including image references for deletion) |
| `settings.py` | the typed `Settings` model and `SettingsStore` (`read`/`write` whole top-level fields; `get`/`set` for prompt switches) |
| `jobs.py`, `artifact_views.py` | `JobsStore` (status, result, delivery in one update) and the invert switches |
| `side_chats.py` | `SideChatsStore`: threads and exchanges |
| `graph.py` | `GraphStore`: the graph ledgers; every mutation advances the revision and notifies after commit |
| `usage.py` | `UsageStore`: one row per billed call |

## Tables

| Table | Migration | Holds |
|---|---|---|
| `settings` | 0001 | key → JSON value, one row per top-level settings field |
| `sessions`, `entries` | 0002 (model columns added in 0003) | sessions with their model pick; the entry log (sequence, entry id, kind, JSON payload), deleted with its session |
| `usage` | 0003, rebuilt in 0006 | per-call usage by request id, role, and source id; a trigger removes a deleted session's rows |
| `jobs`, `artifact_views` | 0004 | kind, status, input, result, delivery state, usage; demo/figure inversion |
| `side_threads`, `side_exchanges` | 0005 | side-chat threads per segment and their exchanges |
| `schema_migrations` | created by the runner | applied migration numbers |
| `graph_nodes`, `graph_node_links`, `graph_chains`, `graph_coverage`, `graph_checkpoints`, `graph_sources`, `graph_source_folders`, `graph_source_placements`, `graph_positions`, `graph_revision` | 0006 | the graph ledgers, organization, positions, and the monotonic revision |

Files outside SQLite: learner images at `<data dir>/images/<sha256>.<ext>` (`show_image` stores PNG
or JPEG; a `read` attachment can also be GIF or WebP), credentials in
`<data dir>/credentials.json`, prompt overrides in `<data dir>/prompts/`, the log at
`<data dir>/logs/verstehen.log` (up to 5 MiB, plus three rotated backups), and downloaded demo
browsers in `<data dir>/browsers/`.

## Rules

- **Short transactions.** A transaction is never held across a model call.
- **Payloads are JSON validated by Pydantic** on the way in and out.
- **Multi-step writes are one transaction:** a job result with its delivery flag, a graph merge
  with its coverage, a compaction marker with its usage, saved markers with their job's
  acknowledgement.
- **Applied migrations never change.** Add a new numbered file and run `make lock-migrations`.
- **A setting is never stored as `null`;** a missing setting reads as its typed default.
- **No LearnHarness data import.** Verstehen starts empty, so formats need not match LH's.

## Traps found in M1–M9

- **Store cannot import session**, which is why the entry models live in `store/entries.py`.
- **Each graph mutation rewrites only the changed ledgers** and notifies `graph-changed` only after
  the commit.
