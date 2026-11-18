# Verstehen: instructions for coding agents

> Status: **draft for review**.

Verstehen is a port of LearnHarness (TypeScript/Next.js) to Python + Pydantic AI, with a Tauri +
SvelteKit desktop app. It keeps LearnHarness's learning flow and knowledge graph **exactly**, with
clearer code. Start with the [README](README.md) reading order.

# No guessing

All design authority belongs to the human. **Never guess a design or implementation decision.** If
anything is ambiguous (naming, behavior, data shapes, UX, defaults, scope boundaries, prompt
wording), STOP and ask the user before going on. If you are "a little unsure", you are unsure: ask.
A wrong guess costs far more than a question. Ask early, ask specific questions, one question at a
time.

First investigate and plan rigorously, asking design questions along the way. Get the plan approved
by the user, and only then implement. Implementation is mechanical execution of an approved plan,
not interpretation.

## Where decisions live

- **Decided** is whatever [`docs/decisions.md`](docs/decisions.md) and
  [`docs/architecture.md`](docs/architecture.md) say. Follow them as written.
- **LearnHarness behavior is the specification.** The Part A docs (`docs/learnharness/`) describe it
  with `file:line` references at LearnHarness commit `a636647`. When a doc and the LearnHarness code
  disagree, the code is right: report the mismatch, don't pick one yourself.
- **A behavior change from LearnHarness** needs a user decision recorded in `docs/decisions.md`.
- **A new decision** made with the user is added to `docs/decisions.md` in the same commit as the
  code that uses it.

## Commands

Run from the repository root:

| Command | What it does |
|---|---|
| `make check` | everything: pytest, ruff check, ruff format --check, pyrefly; svelte-check + TypeScript, ESLint + Prettier, Vitest |
| `make test` | only the tests |
| `make fmt` | fix formatting |

- **Run `make check` before every commit.** Don't commit with failing checks.
- Tests are offline. They use Pydantic AI's `FunctionModel` and a temporary SQLite database.
- **Tests against real models use the user's subscriptions.** Run them only when the user asks.

## Code rules

- **Layout** is in [architecture](docs/architecture.md#repository-layout-q6): one package per
  feature under `backend/src/verstehen/`, the app under `app/`.
- **Dependency direction:** `api` → `session`, `sidechat`, `jobs`, `graph` → `teaching`,
  `providers` → `store`. Never import upwards.
- **Only `store/` runs SQL** or imports `sqlite3`. Schema changes are new numbered migration files;
  never edit an applied migration.
- **The entry log is append-only.** Never update or delete entries.
- **Pydantic AI types stay inside** `teaching/`, `session/` (projection and run loop), and
  `providers/`. The database, API, and UI never see them.
- **Vendored code** in `providers/claude_code/` changes only as recorded in its `VENDORED.md`.
- **Prompts** in `teaching/prompts/` are LearnHarness's prompts. Never reword them without a
  decision.

## Data and secrets

- **Never touch the user's real data** in `~/.local/share/verstehen`. Development and tests always
  set `VERSTEHEN_DATA_DIR` to a separate directory.
- **Never read, print, or commit credentials**: `credentials.json`, the Claude Code login, or the
  ChatGPT tokens.
- Commit only when the user asks, and never push without being asked.
