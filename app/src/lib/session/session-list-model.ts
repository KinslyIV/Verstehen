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

export const visibleSessions = (sessions: SessionItem[], filter: KindFilter) =>
	filter === 'all' ? sessions : sessions.filter((session) => session.kind === filter);

/** The row's second line: what the session waits on or is doing, else how long ago. */
export function sessionMeta(session: SessionItem, now: Date): string {
	const ago = timeAgo(session.updated_at, now);
	if (session.compacting) return 'Compacting context';
	if (session.pending_question) return `Waiting for input · ${ago}`;
	if (session.kind === 'practice' && session.pending_problem) return `Problem waiting · ${ago}`;
	return session.busy ? 'Working…' : ago;
}
