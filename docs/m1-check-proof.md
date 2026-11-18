# M1 task 1: rule proofs

Temporary violations were added, checked, and removed. Each forbidden case exited 1;
allowed cases exited 0. Paths below are from the implementation worktree.

### ruff sqlite3 in api (exit 1)
```text
TID251 `sqlite3` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/api/proof.py:1:8
  |
1 | import sqlite3
  |        ^^^^^^^

Found 1 error.
```

### ruff sqlite3 in session (exit 1)
```text
TID251 `sqlite3` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/session/proof.py:1:8
  |
1 | import sqlite3
  |        ^^^^^^^

Found 1 error.
```

### ruff sqlite3 in jobs (exit 1)
```text
TID251 `sqlite3` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/jobs/proof.py:1:8
  |
1 | import sqlite3
  |        ^^^^^^^

Found 1 error.
```

### ruff sqlite3 in jobs/workers (exit 1)
```text
TID251 `sqlite3` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/jobs/workers/proof.py:1:8
  |
1 | import sqlite3
  |        ^^^^^^^

Found 1 error.
```

### ruff sqlite3 in sidechat (exit 1)
```text
TID251 `sqlite3` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/sidechat/proof.py:1:8
  |
1 | import sqlite3
  |        ^^^^^^^

Found 1 error.
```

### ruff sqlite3 in graph (exit 1)
```text
TID251 `sqlite3` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/graph/proof.py:1:8
  |
1 | import sqlite3
  |        ^^^^^^^

Found 1 error.
```

### ruff sqlite3 in teaching (exit 1)
```text
TID251 `sqlite3` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/teaching/proof.py:1:8
  |
1 | import sqlite3
  |        ^^^^^^^

Found 1 error.
```

### ruff sqlite3 in providers (exit 1)
```text
TID251 `sqlite3` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/providers/proof.py:1:8
  |
1 | import sqlite3
  |        ^^^^^^^

Found 1 error.
```

### ruff aiosqlite in api (exit 1)
```text
TID251 `aiosqlite` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/api/proof.py:1:8
  |
1 | import aiosqlite
  |        ^^^^^^^^^

Found 1 error.
```

### ruff aiosqlite in session (exit 1)
```text
TID251 `aiosqlite` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/session/proof.py:1:8
  |
1 | import aiosqlite
  |        ^^^^^^^^^

Found 1 error.
```

### ruff aiosqlite in jobs (exit 1)
```text
TID251 `aiosqlite` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/jobs/proof.py:1:8
  |
1 | import aiosqlite
  |        ^^^^^^^^^

Found 1 error.
```

### ruff aiosqlite in jobs/workers (exit 1)
```text
TID251 `aiosqlite` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/jobs/workers/proof.py:1:8
  |
1 | import aiosqlite
  |        ^^^^^^^^^

Found 1 error.
```

### ruff aiosqlite in sidechat (exit 1)
```text
TID251 `aiosqlite` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/sidechat/proof.py:1:8
  |
1 | import aiosqlite
  |        ^^^^^^^^^

Found 1 error.
```

### ruff aiosqlite in graph (exit 1)
```text
TID251 `aiosqlite` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/graph/proof.py:1:8
  |
1 | import aiosqlite
  |        ^^^^^^^^^

Found 1 error.
```

### ruff aiosqlite in teaching (exit 1)
```text
TID251 `aiosqlite` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/teaching/proof.py:1:8
  |
1 | import aiosqlite
  |        ^^^^^^^^^

Found 1 error.
```

### ruff aiosqlite in providers (exit 1)
```text
TID251 `aiosqlite` is banned: move this SQL into verstehen.store
 --> backend/src/verstehen/providers/proof.py:1:8
  |
1 | import aiosqlite
  |        ^^^^^^^^^

Found 1 error.
```

### ruff pydantic_ai in api (exit 1)
```text
TID251 `pydantic_ai` is banned: move agent code into verstehen.teaching, verstehen.session, verstehen.providers, verstehen.jobs.workers, verstehen.graph, or verstehen.sidechat
 --> backend/src/verstehen/api/proof.py:1:8
  |
1 | import pydantic_ai
  |        ^^^^^^^^^^^

Found 1 error.
```

### ruff pydantic_ai in store (exit 1)
```text
TID251 `pydantic_ai` is banned: keep stored data independent of Pydantic AI; move agent code into verstehen.teaching or verstehen.providers
 --> backend/src/verstehen/store/proof.py:1:8
  |
1 | import pydantic_ai
  |        ^^^^^^^^^^^

Found 1 error.
```

### ruff pydantic_ai in jobs (exit 1)
```text
TID251 `pydantic_ai` is banned: move agent code into verstehen.teaching, verstehen.session, verstehen.providers, verstehen.jobs.workers, verstehen.graph, or verstehen.sidechat
 --> backend/src/verstehen/jobs/proof.py:1:8
  |
1 | import pydantic_ai
  |        ^^^^^^^^^^^

Found 1 error.
```

### allowed sqlite3 in store (exit 0)
```text
All checks passed!
```

### allowed aiosqlite in store (exit 0)
```text
All checks passed!
```

### allowed pydantic_ai in teaching (exit 0)
```text
All checks passed!
```

### allowed pydantic_ai in session (exit 0)
```text
All checks passed!
```

### allowed pydantic_ai in providers (exit 0)
```text
All checks passed!
```

### allowed pydantic_ai in jobs/workers (exit 0)
```text
All checks passed!
```

### allowed pydantic_ai in graph (exit 0)
```text
All checks passed!
```

### allowed pydantic_ai in sidechat (exit 0)
```text
All checks passed!
```

### layers store imports api (exit 1)
```text
╔══╗─────────▶╔╗ ╔╗      ╔╗◀───┐
╚╣╠╝◀─────┐  ╔╝╚╗║║────▶╔╝╚╗   │
 ║║   ╔══╦══╦╩╗╔╝║║  ╔╦═╩╗╔╝╔═╦══╗
 ║║╔══╣╔╗║╔╗║╔╣║ ║║ ╔╬╣╔╗║║ ║│║╔═╝
╔╣╠╣║║║╚╝║╚╝║║║╚╗║╚═╝║║║║║╚╗║═╣║
╚══╩╩╩╣╔═╩══╩╝╚═╝╚═══╩╩╝╚╩═╩╩═╩╝
  └──▶║║                    ▲ 
      ╚╝────────────────────┘


---------
Contracts
---------

Analyzed 11 files, 1 dependencies.
----------------------------------

Move dependencies down: api -> session -> features -> agents -> store BROKEN

Contracts: 0 kept, 1 broken.


----------------
Broken contracts
----------------

Move dependencies down: api -> session -> features -> agents -> store
---------------------------------------------------------------------

verstehen.store is not allowed to import verstehen.api:

- verstehen.store.proof -> verstehen.api (l.1)


Move dependencies down the declared layers; pass callbacks from session for 
upward notifications.
```

### layers jobs imports graph (exit 1)
```text
╔══╗─────────▶╔╗ ╔╗      ╔╗◀───┐
╚╣╠╝◀─────┐  ╔╝╚╗║║────▶╔╝╚╗   │
 ║║   ╔══╦══╦╩╗╔╝║║  ╔╦═╩╗╔╝╔═╦══╗
 ║║╔══╣╔╗║╔╗║╔╣║ ║║ ╔╬╣╔╗║║ ║│║╔═╝
╔╣╠╣║║║╚╝║╚╝║║║╚╗║╚═╝║║║║║╚╗║═╣║
╚══╩╩╩╣╔═╩══╩╝╚═╝╚═══╩╩╝╚╩═╩╩═╩╝
  └──▶║║                    ▲ 
      ╚╝────────────────────┘


---------
Contracts
---------

Analyzed 11 files, 1 dependencies.
----------------------------------

Move dependencies down: api -> session -> features -> agents -> store BROKEN

Contracts: 0 kept, 1 broken.


----------------
Broken contracts
----------------

Move dependencies down: api -> session -> features -> agents -> store
---------------------------------------------------------------------

verstehen.jobs is not allowed to import verstehen.graph:

- verstehen.jobs.proof -> verstehen.graph (l.1)


Move dependencies down the declared layers; pass callbacks from session for 
upward notifications.
```

### layers teaching imports providers (exit 1)
```text
╔══╗─────────▶╔╗ ╔╗      ╔╗◀───┐
╚╣╠╝◀─────┐  ╔╝╚╗║║────▶╔╝╚╗   │
 ║║   ╔══╦══╦╩╗╔╝║║  ╔╦═╩╗╔╝╔═╦══╗
 ║║╔══╣╔╗║╔╗║╔╣║ ║║ ╔╬╣╔╗║║ ║│║╔═╝
╔╣╠╣║║║╚╝║╚╝║║║╚╗║╚═╝║║║║║╚╗║═╣║
╚══╩╩╩╣╔═╩══╩╝╚═╝╚═══╩╩╝╚╩═╩╩═╩╝
  └──▶║║                    ▲ 
      ╚╝────────────────────┘


---------
Contracts
---------

Analyzed 11 files, 1 dependencies.
----------------------------------

Move dependencies down: api -> session -> features -> agents -> store BROKEN

Contracts: 0 kept, 1 broken.


----------------
Broken contracts
----------------

Move dependencies down: api -> session -> features -> agents -> store
---------------------------------------------------------------------

verstehen.teaching is not allowed to import verstehen.providers:

- verstehen.teaching.proof -> verstehen.providers (l.1)


Move dependencies down the declared layers; pass callbacks from session for 
upward notifications.
```

### comments proof.py (exit 1)
```text
tools/proof.py:1: shorten to at most 3 lines, or let names and types carry the meaning
```

### comments proof.ts (exit 1)
```text
tools/proof.ts:1: shorten to at most 3 lines, or let names and types carry the meaning
```

### comments proof.svelte (exit 1)
```text
tools/proof.svelte:1: shorten to at most 3 lines, or let names and types carry the meaning
```

### eslint fetch (exit 1)
```text
/home/immata/.t3/worktrees/Verstehen/t3-74d0ec5a/app/src/routes/proof.ts
  1:6  error  Unexpected use of 'fetch'. Move HTTP requests into src/lib/api/  no-restricted-globals

✖ 1 problem (1 error, 0 warnings)
```

### eslint window fetch (exit 1)
```text
/home/immata/.t3/worktrees/Verstehen/t3-74d0ec5a/app/src/routes/proof.ts
  1:6  error  Move HTTP requests into src/lib/api/  no-restricted-syntax

✖ 1 problem (1 error, 0 warnings)
```

### eslint generated types (exit 1)
```text
/home/immata/.t3/worktrees/Verstehen/t3-74d0ec5a/app/src/routes/proof.ts
  1:29  error  Move generated API type imports into src/lib/api/; expose app types from the API client  boundaries/dependencies

✖ 1 problem (1 error, 0 warnings)
```

### eslint ui imports app (exit 1)
```text
/home/immata/.t3/worktrees/Verstehen/t3-74d0ec5a/app/src/lib/components/ui/proof.ts
  1:23  error  Move app-specific code out of src/lib/components/ui/; import only UI files, $lib/utils, or npm packages  boundaries/dependencies

✖ 1 problem (1 error, 0 warnings)
```

### eslint lib imports routes (exit 1)
```text
/home/immata/.t3/worktrees/Verstehen/t3-74d0ec5a/app/src/lib/proof.ts
  1:23  error  Move shared code into src/lib/; src/lib/ must never import src/routes/  boundaries/dependencies

✖ 1 problem (1 error, 0 warnings)
```

### allowed UI imports (exit 0)
```text

```

### allowed API fetch and types (exit 0)
```text

```

### unlisted migration (exit 1)
```text
/home/immata/.t3/worktrees/Verstehen/t3-74d0ec5a/backend/src/verstehen/store/migrations/0001_proof.sql: run make lock-migrations to record this new migration
```

### edited migration (exit 1)
```text
/home/immata/.t3/worktrees/Verstehen/t3-74d0ec5a/backend/src/verstehen/store/migrations/0001_proof.sql: add a new numbered migration instead of editing 0001_proof.sql
```

### deleted migration (exit 1)
```text
/home/immata/.t3/worktrees/Verstehen/t3-74d0ec5a/backend/src/verstehen/store/migrations/0001_proof.sql: add a new numbered migration instead of editing 0001_proof.sql
```
