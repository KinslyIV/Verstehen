# LearnHarness import plan

> Status: **approved by the user.** LearnHarness references are to the local clone at
> `/home/immata/learnharness` (record formats: `src/core/contracts/chat.ts`,
> `src/core/native-messages.ts`, `src/core/contracts/jobs.ts`, `src/core/contracts/graph.ts`,
> `src/store/*.ts`, `src/core/coverage.ts`). This feature has no LearnHarness counterpart.

## Overview

A one-way, replace-everything import of a LearnHarness data folder into Verstehen, run from the
command line while the app is closed.

- **New:** package `verstehen.lh_import` (read and validate LH files, convert, write) and a
  sidecar subcommand: `verstehen-sidecar import-learnharness <folder> [--dry-run]`. On the laptop
  the binary is `/usr/lib/verstehen/verstehen-sidecar`; the data dir comes from `load_settings()`
  (`VERSTEHEN_DATA_DIR` or the default).
- **No migration.** Everything fits the existing tables.
- **Layering:** `verstehen.lh_import` sits in the top layer beside `verstehen.api`
  (`"verstehen.api | verstehen.lh_import"` in import-linter); `cli.py` calls it.
- **What the learner notices:** after import and restart, LH's sessions are in the sidebar with
  their questions, jobs, plan, and side chats; the graph shows LH's propositions, chains, sources,
  and layout. Already-extracted messages are not extracted again.

## Run sequence

1. **Read and validate everything** with strict Pydantic models of the LH formats. An unknown
   shape, or a version newer than understood (chat `version` > 2, graph `format.json` > 1), stops
   the import with the file name and nothing is written. Corrupt JSONL lines are skipped, as LH
   does, and reported.
2. **Print a summary:** counts of sessions, messages, jobs, side threads, propositions, chains,
   sources, coverage rows, usage rows; and what is skipped: practice sessions (by title),
   `settings.json`, `prompts/`, `themes/`, `plugins/`, `core-plugin-data/`, `debug/`, `auth.json`.
   `--dry-run` stops here.
3. **Confirm:** the prompt says to close Verstehen first and how many existing sessions and
   propositions will be deleted; the user must type `replace`. Anything else aborts.
4. **Back up** to `<data dir>/backups/before-learnharness-import-<UTC time>/`: the database via
   SQLite's backup API (consistent copy) and a copy of `images/`. A failed backup aborts.
5. **One transaction:** delete all rows of `sessions` (cascades entries, jobs, side chats, artifact
   views), `usage`, and every `graph_*` table, reset `graph_revision`; keep `settings`, provider
   and account tables. Insert all converted records. Image files are written into `images/`
   before the commit (content-addressed, so an aborted run leaves only harmless extra files).
6. **Report:** what was imported and skipped, any warnings, the backup path, and the exact
   restore commands (close the app, copy the database file and `images/` back).

Backups are never deleted automatically.

## Mapping

**Ids are kept as LH wrote them:** session ids, message ids (as `entry_id`), job ids, side thread
and message ids, node and chain ids, source ids. This keeps graph provenance and coverage valid:
Verstehen's fingerprint (`graph/coverage.py`) equals LH's `messageFingerprint` when the entry id
is the LH message id (checked on the user's data: 28 of 28 rows).

| LearnHarness | Verstehen |
|---|---|
| `ChatRecord` `id`, `title`, `createdAt`, `updatedAt` | `sessions` row; `updated_at` kept from LH, so the sidebar order matches |
| `kind: "practice"` | skipped and listed (Verstehen has no practice sessions yet) |
| `settings.model` `{provider: "chatgpt", id}`, `thinkingLevel` | session `model_account` = the ChatGPT account, `model_id`, `thinking_level`. A provider without a Verstehen account leaves the session on the default |
| `UserMessage` (string or text/image blocks) | `UserEntry`; image blocks are dropped with one warning per session (`UserEntry` has no attachments; see decisions) |
| `AssistantMessage` | `AssistantEntry`; `timestamp` ms → ISO UTC `created_at` |
| `stopReason` `toolUse` / `stop` / `length` / `error` / `aborted` | `stop` / `stop` / `length` / `error` / `aborted`; `errorMessage` → `error_text` |
| `provider` `chatgpt` | `openai-chatgpt` (`store/model_identity.py`); others kept as written |
| `model` | kept (the requested model id) |
| `usage` | `EntryUsage` |
| `text` block | `TextPart`; `textSignature` dropped (Verstehen neither stores nor resends it) |
| `thinking` block, ChatGPT: `thinkingSignature` is JSON `{type: "reasoning", id, encrypted_content, summary, content}` | `ThinkingPart(thinking=..., id=<id>, signature=<encrypted_content>)` |
| `thinking` block, other providers | `ThinkingPart(signature=thinkingSignature)`, `redacted` kept |
| `toolCall` | `ToolCallPart` (`id`, `name`, `arguments`) |
| `ToolResultMessage` | `ToolResultEntry`; text blocks joined; image blocks saved to `images/` and referenced as Verstehen's `read` does; `details` converted to Verstehen's model for that tool (question answers → `QuestionAnswer`, `plan_init`, `probe_done`, job dispatch strings, …) and validated |
| `custom` markers | `MarkerEntry` with the same `marker_type`, `content`, `display`; `details` converted to Verstehen's shape: `subagent-steer`/`subagent-abort` → `job_id`, `kind`, `tool_call_id`, `result`; `side-question*` → `thread_id`, `updates`; `plan-block` and `probe-handoff` keep LH's camelCase keys, which Verstehen's consumers read |
| `plugin-problem-submission` marker | refused (plugins are out of scope); not expected in practice |
| job details `ui.inverted` | `artifact_views` row |
| `tree` | not stored: Verstehen derives the plan from the newest `plan_init` result. Warn when the derived tree differs from LH's `tree` |
| `sideChats` threads | `side_threads` (anchor `messageId` → `entry_id`, `blockText`) and `side_exchanges`; `open`, `quoteCitations`, `contextSnapshot` dropped |
| `turns` steps | one `usage` row per step: `request_id` `<turn id>#<n>`, role `prober` before the `probe_done` result else `teacher`, account from the provider, created at the turn's `at` |
| `extractions` (chat) and `sources.json` `extractions` | `usage` rows with roles `extractor` / `auditor`, `session_id` the chat or source id |
| `jobs/*.json` | `jobs` rows. Missing `input` (older records) is rebuilt from the arguments of the tool call with that `toolCallId`; a steer/abort marker for the job settles delivery as `delivered`; a real LH `pending` without a marker stays pending; no `delivery` and no marker leaves delivery unset. A `running` job becomes `error` ("Interrupted by the LearnHarness import"). Job `usage` → the job's usage JSON and its `usage` rows, as Verstehen's jobs record them |
| `graph/nodes.jsonl` | `graph_nodes` (first line per id) and `graph_node_links` (later lines), order kept; `chatId` → `session_id` in provenance |
| `graph/chains.jsonl`, `coverage.jsonl`, `sessions.jsonl` | `graph_chains`, `graph_coverage`, `graph_checkpoints` (`chatId` → `session_id`) |
| `graph/sources.json` (map) | `graph_sources` (`filePath`, `importedAt`) |
| `graph/source-organization.json` (only exists once the user organized sources) | `graph_source_folders`, `graph_source_placements` |
| `graph/positions.json` `{"positions": {...}}` | `graph_positions` |
| — | `graph_revision` = 1 |
| `graph/render-settings.json` | skipped with the other settings |

Write graph rows through `store/graph.py`'s `write_ledger` with an empty previous ledger, so the
node/link split stays in one place.

## Tasks

One task, on branch `learnharness-import` (off `dev`).

1. `backend/src/verstehen/lh_import/`: `records.py` (LH models), `convert.py` (LH → Verstehen),
   `run.py` (summary, confirmation, backup, the replacing transaction, report). Split further only
   if a file gets hard to read.
2. `cli.py`: the `import-learnharness` subcommand beside `--self-check`.
3. `backend/pyproject.toml`: the import-linter layer.
4. Tests and fixtures (below), the verify flow, and the docs.

## Tests (offline)

Fixtures are small, hand-written LH folders under `backend/tests/fixtures/learnharness/`, never
the user's data. Test names follow the behavior, for example:

- `imported_messages_keep_lh_ids_and_coverage_fingerprints` (fingerprints computed by LH's rule
  in the fixture match `coverage_of`, so nothing is uncovered)
- `chatgpt_thinking_signature_becomes_id_and_encrypted_content`, and the projection replays it for
  the same model
- `tool_use_stop_reason_becomes_stop`, `question_answer_details_validate_as_question_answer`,
  `marker_details_use_verstehen_keys`, `read_result_image_is_saved_to_images`
- `job_without_input_takes_tool_call_arguments`, `job_delivery_follows_steer_marker`,
  `running_job_becomes_error`
- `side_chat_threads_and_exchanges_are_imported`, `usage_rows_from_turns_extractions_and_jobs`
- `session_model_pick_from_chatgpt_settings`, `unknown_provider_leaves_session_default`
- `graph_ledger_reads_back`, `positions_are_unwrapped`, `source_organization_is_copied`
- `practice_sessions_are_skipped_and_listed`
- `newer_chat_version_is_refused`, `unknown_record_shape_names_the_file`
- `dry_run_writes_nothing`, `confirmation_other_than_replace_aborts`,
  `backup_is_written_before_replacing`, `failed_import_changes_nothing`,
  `settings_and_accounts_survive_the_import`
- an imported fixture session projects with `to_llm_messages` and loads through the session API

## Verify flow

`learnharness-import`: import the fixture into the flow's data dir, open an imported session
(transcript with an answered question and a job result) and the knowledge graph; screenshot both.
Feature map entry: **LearnHarness import**.

## Checks on real data

- **Dry run and import of the user's copy** (`/home/immata/lh-data/data`, read-only) into a
  throwaway `VERSTEHEN_DATA_DIR`; the summary must show 2 sessions, 6 jobs, 123 propositions
  (145 ledger lines), 63 chains (64 ledger lines), 21 sources, no warnings except expected ones.
- **One real ChatGPT turn** (approved by the user): continue "Learning SIFT" on `gpt-6-astra` in
  that throwaway data dir and confirm the request with the converted reasoning is accepted. Needs a
  signed-in ChatGPT account; if Pixal has none, ask the user before running it on the laptop.

## Docs

`docs/roadmap.md` and `docs/architecture/store.md` drop "No LearnHarness data import"; the store
area doc gets an "Importing from LearnHarness" section (what is imported, skipped, the backup, and
restore steps); feature map; status.
