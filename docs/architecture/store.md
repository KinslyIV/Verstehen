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
| `model_identity.py` | `ModelIdentity`: provider and requested model id shared by projection and token estimates; no Pydantic AI dependency |
| `sessions.py` | `Session` and `SessionsStore` (including image references for deletion) |
| `settings.py` | the typed `Settings` model and `SettingsStore` (`read`/`write` whole top-level fields; `get`/`set` for prompt switches) |
| `jobs.py`, `artifact_views.py` | `JobsStore` (status, result, delivery in one update) and the invert switches |
| `side_chats.py` | `SideChatsStore`: threads and exchanges |
| `graph.py` | `GraphStore`: the graph ledgers; every mutation advances the revision and notifies after commit |
| `usage.py` | `UsageStore`: one row per billed call |
| `devices.py` | `Device` and `DevicesStore`: paired devices, SHA-256-hashed bearer tokens, throttled `last_seen_at`, and revocation |
| `sync_log.py`, `sync.py` | `SyncStore`, changelog helpers, tombstones, `server_seq` LWW tracking, initial snapshot seeding, and fork-on-conflict cloning |
| `replace.py`, `backup.py` | `replace_contents` (delete every session, usage row, and graph row, then write a whole `StoreContents`, in one transaction) and `backup_database` (SQLite's backup API); used only by the LearnHarness import |

The insert statements shared with the LearnHarness import live in each store module as functions
over a connection (`insert_entry`, `insert_session`, `insert_job`, `insert_side_thread`,
`insert_side_exchange`, `set_inverted`, `insert_usage`); the stores call the same functions.

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
| `devices` | 0007 | paired devices (`id`, `name`, `token_hash`, `created_at`, `last_seen_at`, `revoked_at`) |
| `sync_state`, `sync_log`, `sync_tombstones`, `sync_versions`, `sync_prompt_state` | 0008 | two-way sync bookmarks, changelog, delete tombstones, `server_seq` LWW versions, prompt override hashes; adds `sync_id` to graph ledger tables, `updated_at` to mutable tables, and `owner_device_id` to `jobs` |

Files outside SQLite: learner images at `<data dir>/images/<sha256>.<ext>` (`show_image` stores PNG
or JPEG; a `read` attachment can also be GIF or WebP), credentials in
`<data dir>/credentials.json`, prompt overrides in `<data dir>/prompts/`, the log at
`<data dir>/logs/verstehen.log` (up to 5 MiB, plus three rotated backups), and downloaded demo
browsers in `<data dir>/browsers/`.

## Rules

- **Short transactions.** A transaction is never held across a model call.
- **Payloads are JSON validated by Pydantic** on the way in and out. Assistant entries save the
  requested provider and model id; thinking keeps its signature and optional Responses reasoning
  item id. Older entries need no migration, but ChatGPT thinking without an id is not replayed.
- **Multi-step writes are one transaction:** a job result with its delivery flag, a graph merge
  with its coverage, a compaction marker with its usage, saved markers with their job's
  acknowledgement.
- **Applied migrations never change.** Add a new numbered file and run `make lock-migrations`.
- **A setting is never stored as `null`;** a missing setting reads as its typed default.

## Importing from LearnHarness

`verstehen-sidecar import-learnharness <folder> [--dry-run]` (the installed binary is
`/usr/lib/verstehen/verstehen-sidecar`; in development `verstehen import-learnharness`) replaces
Verstehen's sessions and graph with a LearnHarness data folder. It is one-way, runs while the app
is closed, and uses the data directory from `VERSTEHEN_DATA_DIR` or the default. The code is
`backend/src/verstehen/lh_import/`: `records.py` (strict Pydantic models of LH's files; any unknown
field is refused), `reader.py` (reads the folder; names the file in every refusal), `entries.py`
and `convert.py` (LH to Verstehen), `run.py` (summary, confirmation, backup, replace, report).

**Run sequence.**

1. **Read and validate everything.** An unknown shape (including the plan `tree`), a time without
   a zone, a chat `version` above 2, or a graph `format.json` above 1 stops the run with the file
   and field; nothing is written. JSONL files are split on line feeds only, and corrupt lines
   are skipped (as LH does) and listed.
2. **Print a summary:** sessions, messages, jobs, side-chat threads, propositions, chains,
   sources, coverage rows, usage rows, and what is skipped and any warnings. `--dry-run` stops here.
3. **Confirm.** The prompt says to close Verstehen first and how many existing sessions and
   propositions will be deleted; only the typed word `replace` continues. Until the backup is
   written the destination is only read: no directory, database, or migration is created, and the
   counts come from a read-only look at the file as it is.
4. **Back up** to `<data dir>/backups/before-learnharness-import-<UTC time>/`: the database as it
   was before any migration (a consistent copy through SQLite's backup API; none when there is no
   database yet) and `images/`. A failed backup aborts. Backups are never deleted automatically.
5. **Replace in one transaction** (after migrating an older database): every session (with its entries, jobs, side chats, and artifact
   views), the usage table, and every graph table are deleted and rewritten; settings, provider
   settings, and ChatGPT accounts stay. Image files are written before the commit; they are
   content-addressed, so an aborted run leaves only harmless extra files.
6. **Report** what was imported, the backup path, and the restore commands.

**What is imported.** Ids are kept as LH wrote them (sessions, messages as entry ids, jobs, side
threads, nodes, chains, sources), so graph provenance and coverage stay valid: Verstehen's
coverage fingerprint equals LH's when the entry id is the LH message id, so imported messages are
not extracted again. `updated_at` is kept, so the sidebar order matches.

- **Messages** become entries: `toolUse` becomes `stop`; provider `chatgpt` becomes
  `openai-chatgpt`; text signatures are dropped. ChatGPT thinking (provider `chatgpt`;
  `thinkingSignature` is a JSON reasoning item) becomes `ThinkingPart(id, signature=encrypted_content)`,
  which Verstehen replays to the same provider and model; a reasoning item without encrypted
  content is kept as text only. Other providers' signatures are kept verbatim.
- **Tool results** use Verstehen's shapes: question answers become `QuestionAnswer` (snake_case,
  validated; `optionOrder` and answer `images` are dropped), `plan_init` keeps its validated tree,
  job tool results carry no details, `show_image` and `read` images are saved to `images/` and
  referenced as Verstehen's tools do. Markers use Verstehen's keys (`job_id`, `tool_call_id`,
  `thread_id`, compaction ids); a plan block keeps its `planCallId` and `block`.
- **Jobs** keep their ids. A missing `input` is rebuilt from the tool call's arguments. A saved
  steer or abort marker settles delivery as `delivered` (even where LH says `pending`); a real LH
  `pending` without a marker stays pending; a terminal job with neither `delivery` nor marker has
  no delivery, so old results are never replayed. A job still `running` without a result becomes
  `error` ("Interrupted by the LearnHarness import"); one still `running` with a saved result is
  classified into `error` or `done` (`is_failure`) and gets pending result delivery when it has no
  delivery or marker yet, matching LH's `normalizeLegacyResult`. An invert switch becomes an
  artifact view.
- **Side chats** keep their thread ids and exchanges. The anchor moves to the first assistant entry
  of the teaching segment that holds LH's anchor message (`sidechat/segments.py`), which is how
  the Side chat tab finds a thread; threads that cannot be placed are imported and listed in a
  warning.
- **Usage rows** come from the chat's `turns` (role `sideQuestion` for a side reply, `compaction`
  for a compaction marker, `prober` before the `probe_done` result, else `teacher`), its
  `extractions` and the sources' `extractions` (roles `extractor` and `auditor`), and job usage
  (one row per recorded call, or one total row). The account is always `chatgpt:learnharness-import`
  for ChatGPT models (history never claims a local account), `claude_code`, or the provider name
  as written.
- **The session's model** follows LH's chat settings when the provider is `chatgpt` and exactly
  one ChatGPT account is signed in; otherwise the session uses the default and a warning says so.
- **The graph**: nodes (later lines become links), chains, coverage, checkpoints, sources, source
  folders and placements, and positions, written through `write_ledger`; the revision is 1. The
  summary counts propositions and chains as the graph derives them (`get_graph`), with the ledger
  line counts beside them.
- **Warnings** also cover learner-message images (counted per session; Verstehen has no learner
  attachments), a derived
  plan that differs from LH's saved `tree`, jobs of sessions that were not imported, and graph
  rows that name sessions that were not imported.

**Skipped:** practice sessions (listed by title), `settings.json`, `graph/render-settings.json`,
`prompts/`, `themes/`, `plugins/`, `core-plugin-data/`, `debug/`, and `auth.json` (never read).
Plugin problem submissions and plugin jobs are refused.

**Restore.** Close Verstehen, then copy the backup back; the command prints the exact, shell-quoted
lines:

```
cp <backup>/verstehen.db <data dir>/verstehen.db
rm -f <data dir>/verstehen.db-wal <data dir>/verstehen.db-shm
cp -r <backup>/images/. <data dir>/images/
```

The images copy only adds the backed-up files; images saved after the import stay.

## Traps found in M1–M9

- **Store cannot import session**, which is why the entry models live in `store/entries.py`.
- **Each graph mutation rewrites only the changed ledgers** and notifies `graph-changed` only after
  the commit.
