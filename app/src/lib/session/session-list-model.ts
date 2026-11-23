import type { SessionItem } from '#lib/api/client.js';
import { timeAgo } from './time-ago.js';

export type KindFilter = 'teach' | 'practice' | 'all';
export const kindFilters: { value: KindFilter; label: string }[] = [
	{ value: 'teach', label: 'Teaching' },
	{ value: 'practice', label: 'Practice' },
	{ value: 'all', label: 'All' }
];
const storageKey = 'verstehen-session-kind-filter';

export function readKindFilter(): KindFilter {
	try {
		const stored = localStorage.getItem(storageKey);
		return kindFilters.some(({ value }) => value === stored) ? (stored as KindFilter) : 'all';
	} catch {
		return 'all';
	}
}

export function saveKindFilter(filter: KindFilter): void {
	try {
		localStorage.setItem(storageKey, filter);
	} catch {
		/* The filter still applies for this visit. */
	}
}

export const kindIncludes = (filter: KindFilter) => (session: SessionItem) =>
	filter === 'all' || session.kind === filter;

const openFoldersKey = 'verstehen-sidebar-open-folders';

/** The folders the learner left open in this sidebar, remembered on this device. */
export function readOpenFolders(): Set<string> {
	try {
		const stored: unknown = JSON.parse(localStorage.getItem(openFoldersKey) ?? '[]');
		return new Set(Array.isArray(stored) ? stored.filter((id) => typeof id === 'string') : []);
	} catch {
		return new Set();
	}
}

export function saveOpenFolders(ids: ReadonlySet<string>): void {
	try {
		localStorage.setItem(openFoldersKey, JSON.stringify([...ids]));
	} catch {
		/* The folders stay open for this visit. */
	}
}

/** The row's second line: what the session waits on or is doing, else how long ago. */
export function sessionMeta(session: SessionItem, now: Date): string {
	const ago = timeAgo(session.updated_at, now);
	if (session.compacting) return 'Compacting context';
	if (session.pending_question) return `Waiting for input · ${ago}`;
	if (session.kind === 'practice' && session.pending_problem) return `Problem waiting · ${ago}`;
	return session.busy ? 'Working…' : ago;
}
