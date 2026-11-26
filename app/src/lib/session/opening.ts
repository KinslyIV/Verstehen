import type { Entry } from '#lib/api/client.js';

export const OPENING_FAILURE =
	'Couldn’t open the session. Your message is still here. Try sending again.';
const key = (id: string) => `verstehen.opening.${id}`;
export function stashOpening(
	id: string,
	text: string,
	attempted = false,
	notice?: string | null
): void {
	const value = JSON.stringify({ text, attempted, ...(notice ? { notice } : {}) });
	sessionStorage.setItem(key(id), value);
	if (sessionStorage.getItem(key(id)) !== value) throw new Error(OPENING_FAILURE);
}
export function readOpening(
	id: string
): { text: string; attempted: boolean; notice?: string } | undefined {
	try {
		const value = JSON.parse(sessionStorage.getItem(key(id)) ?? 'null');
		if (typeof value?.text === 'string' && typeof value?.attempted === 'boolean') {
			return {
				text: value.text,
				attempted: value.attempted,
				...(typeof value.notice === 'string' && value.notice ? { notice: value.notice } : {})
			};
		}
	} catch {
		return;
	}
}

export function clearOpeningNotice(id: string): void {
	const current = readOpening(id);
	if (!current?.notice) return;
	try {
		stashOpening(id, current.text, current.attempted);
	} catch {
		return;
	}
}

/** A session still awaits its opening message when it holds nothing but a graph-context marker. */
export function awaitsOpening(entries: Entry[]): boolean {
	return entries.every((entry) => entry.kind === 'marker' && entry.marker_type === 'graph-context');
}
