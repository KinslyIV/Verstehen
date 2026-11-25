# Status

> One page: where the project is, the next step, and open questions. History lives in git and the
> PRs. Last update: 2026-11-25 (Qt shell branch `qt-shell` ready for review).

## Where we are

`M1–M9` are merged into `main` (`v0.1.0`): the teaching loop, real providers, question tools,
compaction, background jobs, side chat, and the knowledge graph, plus CI, faster checks, and
tag-driven Arch releases. See the [roadmap](roadmap.md).

Merged into `dev` and queued for `0.2.0` on `main`:

- **Core follow-ups & LearnHarness import:** ChatGPT model-list cache, docs redesign (PR #4),
  slim verification (PR #5), ChatGPT reasoning resend (PR #3; all six orchestrator decisions from
  PR #3 and PR #5 reviewed and kept on 2026-11-21), background worker and extraction
  simplifications (PR #7, PR #10), explain skill (PR #8), and LearnHarness data import
  (`verstehen import-learnharness`, PR #9; one real ChatGPT turn on the imported
  "Learning SIFT" session still has to confirm converted reasoning acceptance).
- **Mobile & sync Milestones A–D** (PR #12–#17; [mobile-and-sync](plans/mobile-and-sync.md),
  [mobile-sync-c](plans/mobile-sync-c.md), [mobile-sync-d](plans/mobile-sync-d.md)): server mode,
  per-device auth and short-code pairing, two-way laptop ↔ server sync, Settings → Sync with SSH
  install/update/rollback and server ChatGPT sign-in (with bounded stop + `SO_REUSEADDR` port
  handover; two Milestone C UI races remain deferred: delayed poll from a replaced sign-in on the
  same pairing, and stale password prompt after reopening Settings and reconnecting during an
  update), Capacitor Android app, remote mode, `/pair`, phone and tablet layouts, `/graph` touch,
  phone Settings, and stream recovery.
- **M10 practice sessions** (PR #14; [plan](plans/m10.md)): practitioner agent, practice dock and
  cards, LearnHarness practice import, solution-safe side chat, and sidebar/graph practice entry
  points (migration `0010`; sync pauses until both backends match schema; LearnHarness replacement
  requires an unpaired local data directory).
- **Desktop responsiveness** (PR #18; [plan](plans/desktop-responsiveness.md)): early shell paint,
  saved model catalogs and stable pickers with Thinking slider, lighter sidebar and graph reads,
  and the prompt editor.
- **M11a** (PR #19; [plan](plans/m11-folders-search-stats.md)): sidebar folders, title search,
  graph folder filter, stats bar, 90% quiz confidence, and prompt editor follow-ups. The
  specification is now LH `069a6a11`; the remaining changes since `cb25c8e` are in the
  [LH catch-up list](roadmap.md#lh-catch-up).
- **Python 3.15 + PEP 810 lazy imports** (PR #20, since reverted to 3.14 for PySide6): backend
  upgraded to Python 3.15
  (`uv >= 0.13.9`), nine heavy SDK/worker imports (`anthropic`, `claude_agent_sdk`, `openai`,
  `asyncssh`, `playwright`, `pypdfium2`, `PIL`, `regex`, `resvg_py`) deferred with module-scope
  `lazy` imports (guarded by `backend/tests/shell/test_startup_imports.py`), plus verify fixture
  and probe-handoff race fixes.
- **UX polish** (branch `ux-polish-folders-width-zoom-minimap`, not yet merged;
  [plan](plans/ux-polish.md)): sidebar folder drag-and-drop fixed on the desktop app, **Move to
  folder** and **New teaching/practice here**, Settings → Appearance → Transcript width, zoom
  popups for demos, figures, and images, the turn minimap rail, and an always-visible
  scroll-to-bottom button. Steps 0–4 are committed; the docs sync is Step 5.
- **Qt shell** (branch `qt-shell`, not yet merged; [plan](plans/qt-shell.md)): PySide6 +
  QtWebEngine replaces Tauri. One process runs the Qt window on the main thread and FastAPI, which
  also serves the app, on a thread; the token is an HttpOnly cookie. Demo checks run in the app's
  own Chromium (`DesktopDemoRunner`; server mode keeps Playwright), the WebKitGTK workarounds are
  gone, off-screen transcript rows are `content-visibility` placeholders, and far demo frames
  unload. Packaging is one PyInstaller onedir app, with no Rust in the build. Heavy libraries are
  imported inside the functions that use them; Python is back on 3.14, since PySide6 breaks
  Python 3.15's PEP 810 `lazy` imports, the standard library's included.
  The package ships only the Qt it loads, in English and German (219 MB, 527 MB installed).
- **Test organization & verification:** 9-area test separation (`AREA=`) across backend pytest,
  frontend Vitest, and 69 scripted Playwright flows. Live Claude verification (`make verify-live`)
  was quota-blocked on 2026-11-21 and still needs a fresh run.

## Next

0. Review and merge the `qt-shell` PR into `dev`. Then, on the laptop with `make app` installed:
   Task 8 (PSS for a demo-free lesson and the 2-demo session; five session switches plus a heap
   snapshot with `VERSTEHEN_DEVTOOLS=1`) and the hand checks: trackpad pinch on the graph,
   folder and file drag-and-drop, and Wayland window flashing and window icon.
0a. Review the UX polish branch, run full `make check` and `make verify`, and open its PR into
   `dev`; check the sidebar folder drag-and-drop in the installed app by hand.
1. Merge `release/0.2.0` into `dev`.
2. Open and merge `dev` → `main` with green GitHub CI (`ci` and `android-debug`), then tag
   `v0.2.0` on `main` to publish the Arch package and signed Android `.apk`.
3. Review the pending [implementation decisions](decisions.md#waiting-for-your-review).
4. Continue M11 (remaining [LH catch-up list](roadmap.md#lh-catch-up), activity dock, themes,
   later providers) and open [known gaps](roadmap.md#known-gaps).

## Open questions

Review the pending [implementation decisions](decisions.md#waiting-for-your-review) from
LearnHarness import, Mobile & Sync A/C/D, Desktop responsiveness, and M11a.
