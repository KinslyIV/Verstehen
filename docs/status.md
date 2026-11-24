# Status

> One page: where the project is, the next step, and open questions. History lives in git and the
> PRs. Last update: 2026-11-23 (M11a built and verified; PR into `dev` ready for review).

## Where we are

M1–M9 are merged into `main`: the teaching loop, real providers, question tools, compaction,
background jobs, side chat, and the knowledge graph, plus CI and tag-driven Arch releases. `dev`
also holds the ChatGPT model-list cache, docs redesign (PR #4), slim verification (PR #5), and
ChatGPT reasoning resend (PR #3). See the [roadmap](roadmap.md).

Full 72-case fake-model verification and live ChatGPT reasoning acceptance passed on PR #3. Live
Claude verification (`make verify-live`) was blocked by the five-hour subscription quota (reset at
17:00 UTC on 2026-11-21) and still needs to be rerun. All six orchestrator decisions from PR #3 and
PR #5 were reviewed and kept on 2026-11-21.

The LearnHarness import (`verstehen-sidecar import-learnharness`) is built on `learnharness-import`
and waits for review; one real ChatGPT turn on the imported "Learning SIFT" session still has to
confirm that converted reasoning is accepted.

Mobile & sync Milestones A and B are merged into `dev`. The combined integration PR (#14)
added:

- **Mobile & sync Milestone C** ([plan](plans/mobile-sync-c.md)): Settings → Sync and the sidebar
  badge, SSH install and update with host trust and health-gated rollback, server ChatGPT account
  sign-in, and device pairing and revocation. The server-side install lock serializes deployment
  and recovery. Updates verify the responding systemd invocation and schema. Rollback retains
  recovery files when the previous wheel cannot read the upgraded database.
  Server updates survive a slow stop of the old server: the unit stops within 15 s, the server
  binds with `SO_REUSEADDR` and bounds its graceful shutdown, and the installer waits past both, including the 60 s TIME_WAIT of a first upgrade.
  Two UI races are deferred: a delayed poll from a replaced sign-in on the same
  pairing, and a stale password prompt after reopening Settings and reconnecting during an update.
- **M10 practice sessions** ([plan](plans/m10.md)): the practitioner, practice dock and cards,
  LearnHarness practice import, solution-safe side chat, and practice entry points in the sidebar
  and graph. Migration `0010` follows Milestone C's `0009`. Sync pauses until both backends run
  the same schema version. LearnHarness replacement requires an unpaired local data directory.
- **Test organization:** backend pytest files, frontend Vitest globs, and browser flows are
  organized into nine areas with `AREA=` selection. The reorganization consolidated 72 flows into
  49. Milestone C and M10 bring the total to 52; Milestone D adds `mobile-pair` and six phone flows for 59.

The desktop responsiveness branch adds early shell paint, saved model catalogs and stable
pickers with a Thinking slider, lighter sidebar and graph reads, and a prompt editor. It adds four
scripted flows, bringing the total to 63. Native trackpad zoom on Arch and long-transcript
rendering remain open.

The Python 3.15 + PEP 810 lazy imports branch upgrades the backend to Python 3.15 (`uv >= 0.13.9`)
and defers heavy SDK/worker imports (`anthropic`, `claude_agent_sdk`, `openai`, `asyncssh`,
`playwright`, `pypdfium2`, `PIL`, `regex`, `resvg_py`) with module-scope `lazy` imports, guarded
by `backend/tests/shell/test_startup_imports.py`.

## Next

1. **M11a** ([plan](plans/m11-folders-search-stats.md)) on `m11-folders-search-stats`: sidebar
   folders, title search, graph folder filter, stats bar, 90% quiz confidence, and the prompt
   editor follow-ups (built and verified across four review rounds; adds six flows for 69 total;
   PR into `dev` ready alongside [implementation decisions](decisions.md#waiting-for-your-review)).
   The specification is now LH `069a6a11`; the other changes since `cb25c8e` are the
   [LH catch-up list](roadmap.md#lh-catch-up).
2. Review the desktop responsiveness changes and [implementation decisions](decisions.md#waiting-for-your-review).
3. Mobile & sync Milestone D ([plan](plans/mobile-sync-d.md)): PR #15 (the Capacitor Android app,
   remote mode, `/pair`, and Android build tooling) and PR #16 (the phone and tablet layouts,
   `/graph` touch, phone Settings, and stream recovery) are merged into `dev`. Next is M11.
4. Merge `dev` into `main` after addressing the [known gaps](roadmap.md#known-gaps) that affect CI.

## Open questions

Review the [implementation decisions](decisions.md#waiting-for-your-review) from the integration PR (#14, merged into `dev`).
