import type { Entry, ToolCallPart } from '#lib/api/client.js';
import { parseJson } from '#lib/questions/question-core.js';
import { asObject } from '#lib/questions/question-input.js';

export const PROBLEM_TOOL = 'problem';
export const CONCLUDE_TOOL = 'conclude';

export interface ActiveProblem {
	toolCallId: string;
	statement: string;
}

const cleanResultIds = (entries: Entry[]) =>
	new Set(
		entries.flatMap((entry) =>
			entry.kind === 'tool_result' && !entry.is_error ? [entry.tool_call_id] : []
		)
	);

const calls = (entry: Entry): ToolCallPart[] =>
	entry.kind === 'assistant'
		? entry.parts.filter((part): part is ToolCallPart => part.type === 'tool_call')
		: [];

/** The newest cleanly posed problem with no clean conclusion or dismissal after it. */
export function activeProblemOf(entries: Entry[]): ActiveProblem | undefined {
	const clean = cleanResultIds(entries);
	for (const entry of entries.toReversed()) {
		if (entry.kind === 'marker' && entry.marker_type === 'problem-dismissed') return;
		for (const part of calls(entry).toReversed()) {
			if (part.tool_name === CONCLUDE_TOOL && clean.has(part.tool_call_id)) return;
			if (part.tool_name === PROBLEM_TOOL && clean.has(part.tool_call_id)) {
				const statement = asObject(parseJson(part.arguments))?.statement;
				return {
					toolCallId: part.tool_call_id,
					statement: typeof statement === 'string' ? statement : ''
				};
			}
		}
	}
}

/** The dismissed problem's call id while its conclude synthesis still awaits the next input. */
export function pendingProblemDismissalOf(entries: Entry[]): string | undefined {
	const clean = cleanResultIds(entries);
	for (const entry of entries.toReversed()) {
		if (entry.kind === 'marker' && entry.marker_type === 'problem-dismissed') {
			const id = asObject(entry.details)?.problem_call_id;
			return typeof id === 'string' && id ? id : undefined;
		}
		if (
			calls(entry).some(
				(part) =>
					[PROBLEM_TOOL, CONCLUDE_TOOL].includes(part.tool_name) && clean.has(part.tool_call_id)
			)
		)
			return;
	}
}

/** The arguments of the newest cleanly posed problem before the given conclude call. */
export function problemInputForConclude(
	entries: Entry[],
	concludeCallId: string
): Record<string, unknown> | undefined {
	const concludeAt = entries.findIndex((entry) =>
		calls(entry).some((part) => part.tool_call_id === concludeCallId)
	);
	if (concludeAt < 0) return;
	const clean = cleanResultIds(entries);
	for (let index = concludeAt; index >= 0; index--) {
		let parts = calls(entries[index]!);
		if (index === concludeAt)
			parts = parts.slice(
				0,
				parts.findIndex((part) => part.tool_call_id === concludeCallId)
			);
		const pose = parts.findLast(
			(part) => part.tool_name === PROBLEM_TOOL && clean.has(part.tool_call_id)
		);
		if (pose) return asObject(parseJson(pose.arguments));
	}
}

/** The solution committed with the pose, shown verbatim when the problem ends. */
export function modelSolutionForConclude(
	entries: Entry[],
	concludeCallId: string
): string | undefined {
	const solution = problemInputForConclude(entries, concludeCallId)?.modelSolution;
	return typeof solution === 'string' ? solution : undefined;
}

/** Whether a tool-result batch holds a clean problem pose acknowledgement. */
export function hasProblemPose(results: Entry[]): boolean {
	return results.some(
		(entry) =>
			entry.kind === 'tool_result' &&
			!entry.is_error &&
			entry.tool_name === PROBLEM_TOOL &&
			entry.details == null
	);
}

/** Whether any problem was ever cleanly posed, so the move-on to a next problem applies. */
export function hasPosedProblem(entries: Entry[]): boolean {
	const clean = cleanResultIds(entries);
	return entries.some((entry) =>
		calls(entry).some((part) => part.tool_name === PROBLEM_TOOL && clean.has(part.tool_call_id))
	);
}
