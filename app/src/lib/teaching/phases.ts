import type { Entry } from '#lib/api/client.js';
import { asObject } from '#lib/questions/question-input.js';
import { parseJson } from '#lib/questions/question-core.js';

export type Phase = 'probe' | 'plan' | 'teach';
export const phaseLabel: Record<Phase, string> = {
	probe: 'Probing',
	plan: 'Planning',
	teach: 'Teaching'
};

export type AssistantPart = Extract<Entry, { kind: 'assistant' }>['parts'][number];

export function taggedNodeId(part: AssistantPart): string | undefined {
	if (part.type !== 'tool_call' || !['quiz', 'explain'].includes(part.tool_name)) return;
	const id = asObject(parseJson(part.arguments))?.nodeId;
	if (typeof id === 'string' && id.length > 0) return id;
}

/** Each assistant entry is one provider step; its index is the divider seam. */
export function teachStepIndex(entries: Entry[], start = 0): number {
	return entries.findIndex(
		(entry, index) => index >= start && entry.kind === 'assistant' && entry.parts.some(taggedNodeId)
	);
}

export function phaseTimeline(entries: Entry[]) {
	const timeline: Phase[] = [];
	const calls = new Set<string>();
	let phase: Phase = 'probe';
	let owed = false;
	let teachAt = -1;
	for (const [index, entry] of entries.entries()) {
		if (entry.kind === 'assistant') {
			if (entry.stop_reason !== 'error' && entry.stop_reason !== 'aborted') {
				for (const part of entry.parts) {
					if (part.type === 'tool_call' && part.tool_name === 'probe_done')
						calls.add(part.tool_call_id);
				}
			}
		} else if (
			entry.kind === 'tool_result' &&
			entry.tool_name === 'probe_done' &&
			calls.has(entry.tool_call_id) &&
			!entry.is_error &&
			asObject(entry.details)?.ok !== false
		) {
			owed = true;
			if (phase === 'probe') {
				phase = 'plan';
				teachAt = teachStepIndex(entries, index + 1);
			}
		} else if (
			entry.kind === 'user' ||
			(entry.kind === 'marker' && entry.marker_type === 'probe-handoff')
		) {
			owed = false;
		}
		if (index === teachAt) phase = 'teach';
		timeline.push(phase);
	}
	return { timeline, teachAt, owed };
}
