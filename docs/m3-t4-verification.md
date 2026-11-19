# M3 T4 verification evidence

Verified on `m3-t4-ui`, based on reviewed providers commit `d7e2ae0`, with the complete T4
working tree. The final application source stayed unchanged through the passing full UI run.

- `make check`: passed, **334 Python tests, 80 Vitest tests**; two opt-in live cases deselected.
  Svelte reported zero errors and warnings. API-type freshness, lint, formatting, imports,
  comment rules, migration locks, and version checks passed.
- `make verify FLOW='--workers=1'`: **31/31 passed**, all flows, in 4.4 minutes.
  Every screenshot below was opened and inspected. Each adjacent `trace.zip` is retained.
- `make app`: passed on the final source in **276 seconds**, including frozen dependency checks,
  sidecar health/token/migration/shutdown smoke checks, Tauri compilation, and Arch packaging.
  Artifact: `dist/verstehen-0.1.0-1-x86_64.pkg.tar.zst`.

Earlier concurrent runs hit sidecar startup timeouts and the existing frontend conflict-poll
20 ms deadline. Two-worker full verification hit the known brief Stop-button timing assertion
in the performance flows. Both unchanged performance cases passed in the targeted guarded rerun,
then in the final serial full suite. Assertions and timeouts were not weakened.
The existing long-reply responsiveness limitation remains documented in status.

The account cases mock every account API route and intercept the OAuth popup URL at browser
context scope. They cover all four Claude Code states in both themes, sign-in again, removal,
Add account, background switches, and download progress/completion. The unavailable-model flow
mocks a removed session account and refusal; offline API tests cover the actual backend refusal.
All sidecars use the fake adapter and temporary data. No real models, credentials, or user data
were used. Live sign-in and the desktop window remain for the user to check on the Arch laptop.

## Inspected screenshots

- [app/verify-output/app-reaches-sidecar.flow.ts-app-reaches-sidecar/screenshot.png](../app/verify-output/app-reaches-sidecar.flow.ts-app-reaches-sidecar/screenshot.png)
- [app/verify-output/layout-lesson-dark.flow.ts-layout-lesson-dark/screenshot.png](../app/verify-output/layout-lesson-dark.flow.ts-layout-lesson-dark/screenshot.png)
- [app/verify-output/layout-right-panel-open.flow.ts-layout-right-panel-open/screenshot.png](../app/verify-output/layout-right-panel-open.flow.ts-layout-right-panel-open/screenshot.png)
- [app/verify-output/layout-sidebar-collapsed.flow.ts-layout-sidebar-collapsed/screenshot.png](../app/verify-output/layout-sidebar-collapsed.flow.ts-layout-sidebar-collapsed/screenshot.png)
- [app/verify-output/markdown-rendering.flow.ts-markdown-rendering-dark/screenshot.png](../app/verify-output/markdown-rendering.flow.ts-markdown-rendering-dark/screenshot.png)
- [app/verify-output/markdown-rendering.flow.ts-markdown-rendering-light/screenshot.png](../app/verify-output/markdown-rendering.flow.ts-markdown-rendering-light/screenshot.png)
- [app/verify-output/model-menu-session.flow.ts-model-menu-session/screenshot.png](../app/verify-output/model-menu-session.flow.ts-model-menu-session/screenshot.png)
- [app/verify-output/model-menu-slots.flow.ts-model-menu-slots/screenshot.png](../app/verify-output/model-menu-slots.flow.ts-model-menu-slots/screenshot.png)
- [app/verify-output/model-unavailable.flow.ts-model-unavailable/screenshot.png](../app/verify-output/model-unavailable.flow.ts-model-unavailable/screenshot.png)
- [app/verify-output/session-error-retry.flow.ts-session-error-retry/screenshot.png](../app/verify-output/session-error-retry.flow.ts-session-error-retry/screenshot.png)
- [app/verify-output/session-model-title.flow.ts-session-model-title/screenshot.png](../app/verify-output/session-model-title.flow.ts-session-model-title/screenshot.png)
- [app/verify-output/session-new-and-stream.flow.ts-session-new-and-stream-dark/screenshot.png](../app/verify-output/session-new-and-stream.flow.ts-session-new-and-stream-dark/screenshot.png)
- [app/verify-output/session-new-and-stream.flow.ts-session-new-and-stream-light/screenshot.png](../app/verify-output/session-new-and-stream.flow.ts-session-new-and-stream-light/screenshot.png)
- [app/verify-output/session-performance-realis-1d389-ssion-performance-realistic/screenshot.png](../app/verify-output/session-performance-realis-1d389-ssion-performance-realistic/screenshot.png)
- [app/verify-output/session-performance.flow.ts-session-performance/screenshot.png](../app/verify-output/session-performance.flow.ts-session-performance/screenshot.png)
- [app/verify-output/session-reload-mid-turn.flow.ts-session-reload-mid-turn/screenshot.png](../app/verify-output/session-reload-mid-turn.flow.ts-session-reload-mid-turn/screenshot.png)
- [app/verify-output/session-rename-delete.flow.ts-session-rename-delete/screenshot.png](../app/verify-output/session-rename-delete.flow.ts-session-rename-delete/screenshot.png)
- [app/verify-output/session-stop.flow.ts-session-stop/screenshot.png](../app/verify-output/session-stop.flow.ts-session-stop/screenshot.png)
- [app/verify-output/session-thinking-streaming-8b812-ion-thinking-streaming-dark/screenshot.png](../app/verify-output/session-thinking-streaming-8b812-ion-thinking-streaming-dark/screenshot.png)
- [app/verify-output/session-thinking-streaming-beaf3-on-thinking-streaming-light/screenshot.png](../app/verify-output/session-thinking-streaming-beaf3-on-thinking-streaming-light/screenshot.png)
- [app/verify-output/settings-accounts.flow.ts--45903-ccounts-light-not-installed/screenshot.png](../app/verify-output/settings-accounts.flow.ts--45903-ccounts-light-not-installed/screenshot.png)
- [app/verify-output/settings-accounts.flow.ts--ac253-accounts-dark-not-installed/screenshot.png](../app/verify-output/settings-accounts.flow.ts--ac253-accounts-dark-not-installed/screenshot.png)
- [app/verify-output/settings-accounts.flow.ts-settings-accounts-dark-tested/screenshot.png](../app/verify-output/settings-accounts.flow.ts-settings-accounts-dark-tested/screenshot.png)
- [app/verify-output/settings-accounts.flow.ts-settings-accounts-dark-too-old/screenshot.png](../app/verify-output/settings-accounts.flow.ts-settings-accounts-dark-too-old/screenshot.png)
- [app/verify-output/settings-accounts.flow.ts-settings-accounts-dark-untested/screenshot.png](../app/verify-output/settings-accounts.flow.ts-settings-accounts-dark-untested/screenshot.png)
- [app/verify-output/settings-accounts.flow.ts-settings-accounts-light-tested/screenshot.png](../app/verify-output/settings-accounts.flow.ts-settings-accounts-light-tested/screenshot.png)
- [app/verify-output/settings-accounts.flow.ts-settings-accounts-light-too-old/screenshot.png](../app/verify-output/settings-accounts.flow.ts-settings-accounts-light-too-old/screenshot.png)
- [app/verify-output/settings-accounts.flow.ts-settings-accounts-light-untested/screenshot.png](../app/verify-output/settings-accounts.flow.ts-settings-accounts-light-untested/screenshot.png)
- [app/verify-output/settings-appearance-light.flow.ts-settings-appearance-light/screenshot.png](../app/verify-output/settings-appearance-light.flow.ts-settings-appearance-light/screenshot.png)
- [app/verify-output/settings-models-light.flow.ts-settings-models-light/screenshot.png](../app/verify-output/settings-models-light.flow.ts-settings-models-light/screenshot.png)
- [app/verify-output/setup-dialog.flow.ts-setup-dialog/screenshot.png](../app/verify-output/setup-dialog.flow.ts-setup-dialog/screenshot.png)
