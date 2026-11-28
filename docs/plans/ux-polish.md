# UX Polish — Folders, Desktop Chat Width, Artifact Zoom, Turn Minimap & Scroll-to-Bottom

> Status: **approved by the user (2026-11-24).**
> Branch: `ux-polish-folders-width-zoom-minimap` off `dev`.

## Overview

- **What changes:**
  1. **Workflow & review rules (`AGENTS.md`, `docs/workflow.md`, verify skill):** subagents only run scoped checks and verify flows for their own changes (never the full test or verify suite), the orchestrator runs full `make check` and `make verify` once before opening a PR into `dev`, and reviews/fixes only target plausible real bugs rather than impossible edge cases.
  2. **Sidebar folders fix + actions:** fix desktop WebKitGTK HTML5 drag-and-drop (`"dragDropEnabled": false` in `app/src-tauri/tauri.conf.json`, `draggable={false}` on `<a href>` in `session-list.svelte`, `text/plain` + `DRAG_TYPE` payload in `source-drag-row.svelte`, and in-memory fallback in `source-drop.svelte.ts`); add **Move to folder** submenu on the session context menu; add **New teaching here** and **New practice here** on the folder context menu wired to optional `folder_id` on `POST /api/sessions` (no DB migration).
  3. **Adjustable desktop chat width:** add **Settings → Appearance → Transcript width** slider (`46–120rem` in `2rem` steps + **Full** default), stored per device in `localStorage`, applied pre-paint via `--verstehen-transcript-max` on the lesson transcript (composer and docks stay fixed, as in LearnHarness).
  4. **Zoom popups for demos, SVG figures, and learner images:** wrap `demo-card.svelte` in an in-place native `<dialog>.showModal()` with a height-holding spacer while open so live iframe state is preserved across zoom, plus `demo-escape` bridge forwarding; add native `<dialog>.showModal()` zoom popups to `visual-card.svelte` and `image-card.svelte`.
  5. **Turn minimap rail & scroll-to-bottom button:** desktop/tablet fine-pointer left-edge vertical tick rail (one tick per user message, answered question card, or practice problem) with fisheye hover magnification, floating preview card, and click-to-jump; always mount `<Scroller.Button>` (removing `{#if !pending}`) with elevated visibility styling.

## User decisions

- **Verification & review scope:** Option A — subagents verify only their own changes; orchestrator runs full `make check` and `make verify` once before opening a PR into `dev`; review findings and fixes cover plausible real bugs only.
- **Desktop chat width:** Option A — Settings → Appearance → Transcript width slider (`46–120rem` + **Full** default) in `localStorage`, without adaptive 2-column question layout yet.
- **Artifact zoom popups:** Option B for demos (in-place `<dialog>.showModal()` with placeholder spacer preserving live iframe state), plus zoom popups for SVG figures and learner images.
- **Turn minimap rail:** Option A — one tick per exchange (typed user messages, answered question cards, practice problems) on desktop/tablet fine pointers only (hidden on phone `< 768px` and coarse touch pointers).
- **Folders:** fix desktop drag-and-drop, add **Move to folder** on sessions (works on desktop and touch), and add **New teaching here** / **New practice here** on folders.

## Tasks (commit order)

### 0. Workflow docs and approved plan (orchestrator) — done (`35fc960`)
- `AGENTS.md`, `docs/workflow.md`, `.claude/skills/verify/SKILL.md`, `.agents/skills/verify/SKILL.md`, `docs/plans/ux-polish.md`.

### 1. Folders — DnD fix, Move to folder, New teaching/practice here — done (`386889d`)
- Files: `app/src-tauri/tauri.conf.json`, `app/src/lib/api/tauri-config.test.ts`, `app/src/lib/components/session-list.svelte`, `app/src/lib/components/sidebar-folder-row.svelte`, `app/src/lib/components/new-session.svelte`, `app/src/lib/graph/source-drag-row.svelte`, `app/src/lib/graph/source-drop.svelte.ts`, `app/src/lib/graph/source-organization.ts`, `app/src/lib/graph/source-organization.test.ts`, `app/src/lib/graph/source-drop.svelte.test.ts`, `backend/src/verstehen/api/sessions.py`, `backend/src/verstehen/session/sessions.py`, `app/src/lib/api/client.ts`, `app/src/lib/api/schema.d.ts`, `backend/tests/session/test_session_list.py`, `app/verify/shell/sidebar-folders.flow.ts`, `app/verify/shell/mobile-sidebar-folders.flow.ts`.
- Scoped check: `make check AREA='session graph shell'` and `make verify FLOW='sidebar-folders mobile-sidebar-folders'`.

### 2. Desktop chat width (Settings → Appearance → Transcript width) — done (`80905a0`)
- Files: `app/src/lib/layout/transcript-width.svelte.ts`, `app/src/lib/layout/transcript-width.test.ts`, `app/src/app.html`, `app/src/routes/layout.css`, `app/src/lib/components/settings.svelte`, `app/src/lib/components/settings.svelte.test.ts`, `app/src/lib/components/session-thread.svelte`, `app/src/lib/components/composer.svelte`, `app/src/lib/questions/question-dock.svelte`, `app/src/lib/practice/practice-dock.svelte`, `app/src/lib/components/stats-bar.svelte`, `app/src/lib/components/new-session.svelte`, `app/verify/shell/settings.flow.ts`.
- Scoped check: `make check AREA='shell session'` and `make verify FLOW='settings shell-layout'`.

### 3. Zoom popups (demos, SVG figures, learner images) — done (`381409e`)
- Files: `app/src/lib/jobs/jobs.ts`, `app/src/lib/jobs/jobs.test.ts`, `app/src/lib/jobs/demo-card.svelte`, `app/src/lib/jobs/visual-card.svelte`, `app/src/lib/jobs/cards.svelte.test.ts`, `app/src/lib/teaching/image-card.svelte`, `app/src/lib/teaching/image-card.svelte.test.ts`, `app/verify/jobs/job-demo.flow.ts`, `app/verify/jobs/job-visual-annotate.flow.ts`, `app/verify/teaching/show-image.flow.ts`.
- Scoped check: `make check AREA='jobs teaching'` and `make verify FLOW='job-demo job-visual-annotate show-image'`.

### 4. Side turn-minimap rail & scroll-to-bottom button — done (`75736d8`)
- Files: `app/src/lib/session/turn-minimap.ts`, `app/src/lib/session/turn-minimap.test.ts`, `app/src/lib/session/turn-minimap.svelte`, `app/src/lib/session/turn-minimap.svelte.test.ts`, `app/src/lib/components/session-thread.svelte`, `app/verify/session/thread-navigation.flow.ts`, `docs/feature-map.md`.
- Scoped check: `make check AREA='session shell'` and `make verify FLOW='thread-navigation question-collapse mobile-question-dock'`.

### 5. Docs sync, GPT-6.2 Sol review rounds, full verification & PR into `dev`
- Update `docs/decisions.md`, `docs/architecture/{frontend-shell,jobs,session}.md`, `docs/feature-map.md`, and `docs/status.md`.
- Independent review rounds with GPT-6.2 Sol (`reasoningEffort: "medium"`, `serviceTier: "default"`).
- Final `make check` and `make verify` by orchestrator, inspect screenshots, push branch, open PR into `dev`.
