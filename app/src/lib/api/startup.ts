import { invoke, isTauri } from '@tauri-apps/api/core';

export type StartupMark = 'ui_mounted' | 'models_displayed' | 'composer_usable';
const marked = new Set<StartupMark>();

/** Record a startup milestone once: a performance mark, and a timing line in the desktop shell's log. */
export function markStartup(name: StartupMark): void {
	if (marked.has(name)) return;
	marked.add(name);
	performance.mark(`verstehen:${name}`);
	if (isTauri()) void invoke('startup_mark', { name }).catch(() => {});
}
