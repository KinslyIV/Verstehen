import type { Entry, ToolResult } from '#lib/api/client.js';
import { asObject } from '#lib/questions/question-input.js';
import { parseJson } from '#lib/questions/question-core.js';

export function sendToUserText(args: unknown, streaming: boolean): string | undefined {
	let message = asObject(parseJson(args))?.message;
	if (message === undefined && streaming && typeof args === 'string') {
		const prefix = /^\s*\{\s*"message"\s*:\s*"((?:[^"\\]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*)/.exec(
			args
		);
		if (prefix) message = parseJson('"' + prefix[1] + '"');
	}
	if (typeof message === 'string' && message.trim()) return message;
}

export function probeAssessment(args: unknown) {
	const assessment = asObject(asObject(parseJson(args))?.assessment);
	const strands: unknown = assessment?.strands;
	if (!Array.isArray(strands) || !strands.length) return;
	const parsed = strands.map(asObject);
	if (
		!parsed.every(
			(strand) => typeof strand?.strand === 'string' && typeof strand.assessment === 'string'
		)
	)
		return;
	if (assessment?.summary !== undefined && typeof assessment.summary !== 'string') return;
	return {
		strands: parsed as { strand: string; assessment: string }[],
		summary: assessment?.summary
	};
}

/** Index adjacent results by assistant occurrence, since providers can reuse call IDs. */
export function responseResults(entries: Entry[]) {
	const responses = new Map<string, Map<string, ToolResult>>();
	let owner: string | undefined;
	for (const entry of entries) {
		if (entry.kind === 'assistant') owner = entry.entry_id;
		else if (entry.kind === 'tool_result' && owner) {
			const results = responses.get(owner) ?? new Map<string, ToolResult>();
			results.set(entry.tool_call_id, entry);
			responses.set(owner, results);
		} else if (
			entry.kind === 'user' ||
			(entry.kind === 'marker' && entry.marker_type === 'probe-handoff')
		) {
			owner = undefined;
		}
	}
	return responses;
}
