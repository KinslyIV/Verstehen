import type { Entry } from '#lib/api/client.js';
import { asObject } from '#lib/questions/question-input.js';

type MarkerEntry = Extract<Entry, { kind: 'marker' }>;

function isCompaction(entry: Entry): entry is MarkerEntry {
	return entry.kind === 'marker' && entry.marker_type === 'compaction';
}

function detail(marker: MarkerEntry, key: string): unknown {
	return asObject(marker.details)?.[key];
}

export interface CompactionDividers {
	/** Entry the cut divider sits before: the active compaction's first kept entry. */
	cutBefore?: { entryId: string; tokensBefore: number };
	/** How many "Context compacted" lines follow each entry id. */
	momentsAfter: Map<string, number>;
}

/** Place the moment lines at the summarized end and the cut divider before the kept entry. */
export function compactionDividers(entries: Entry[]): CompactionDividers {
	const ids = new Set(entries.map((entry) => entry.entry_id));
	const momentsAfter = new Map<string, number>();
	let active: MarkerEntry | undefined;
	for (const entry of entries.toReversed()) {
		if (!isCompaction(entry)) continue;
		const summarized = detail(entry, 'last_summarized_entry_id');
		const anchor =
			typeof summarized === 'string' && ids.has(summarized) ? summarized : entry.entry_id;
		if (anchor) momentsAfter.set(anchor, (momentsAfter.get(anchor) ?? 0) + 1);
		if (!active && typeof detail(entry, 'first_kept_entry_id') === 'string') active = entry;
	}
	const keptId = active && detail(active, 'first_kept_entry_id');
	const tokens = active && detail(active, 'tokens_before');
	const cutBefore =
		typeof keptId === 'string' && ids.has(keptId)
			? { entryId: keptId, tokensBefore: typeof tokens === 'number' ? tokens : 0 }
			: undefined;
	return { cutBefore, momentsAfter };
}

/** The cut divider's chip text, with the rounded token count when known. */
export function cutDividerText(tokensBefore: number): string {
	return tokensBefore > 0
		? `History compacted · ${Math.round(tokensBefore / 1000)}k tok`
		: 'History compacted';
}

const skippedMarkers = ['plan-block', 'side-question', 'side-question-told'];

/** The failed reply at the end of the log, skipping tool results and display markers. */
export function failedResponseAtEnd(
	entries: Entry[]
): { errorText: string; afterCompaction: boolean } | undefined {
	let afterCompaction = false;
	for (const entry of entries.toReversed()) {
		if (entry.kind === 'marker' && entry.marker_type === 'compaction') afterCompaction = true;
		else if (entry.kind === 'tool_result') continue;
		else if (entry.kind === 'marker' && skippedMarkers.includes(entry.marker_type)) continue;
		else if (entry.kind === 'assistant' && entry.stop_reason === 'error')
			return { errorText: entry.error_text ?? 'An error occurred.', afterCompaction };
		else return;
	}
}

export const compactionLimitDefault = 150_000;
const compactionLimitFloor = 32_000;

/** Read the limit field: null is empty (the default), undefined is invalid input. */
export function parseCompactionLimit(text: string): number | null | undefined {
	if (text.trim() === '') return null;
	const limit = Number(text);
	if (!Number.isFinite(limit) || limit <= 0) return undefined;
	return Math.max(compactionLimitFloor, Math.round(limit));
}
