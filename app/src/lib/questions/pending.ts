import type { Entry, ToolCallPart } from '#lib/api/client.js';
import { questionKinds, type Question, type QuestionTool } from './question-core.js';
import { asObject, parseQuestionInput } from './question-input.js';

export interface QuestionOccurrence {
	toolCallId: string;
	messageId: string;
	contentIndex: number;
	key: string;
}

export interface PendingQuestion extends QuestionOccurrence {
	question: Question;
}

export function questionCallsOf(entries: Entry[], streamingEntryId?: string) {
	const resolved = new Set<string>();
	for (let i = entries.length - 1; i >= 0; i--) {
		const entry = entries[i]!;
		if (entry.kind === 'tool_result') resolved.add(entry.tool_call_id);
		if (entry.kind !== 'assistant') continue;
		if (
			entry.entry_id === streamingEntryId ||
			entry.stop_reason === 'error' ||
			entry.stop_reason === 'aborted'
		)
			return [];
		return entry.parts.flatMap((part, contentIndex) => {
			if (
				part.type !== 'tool_call' ||
				!Object.hasOwn(questionKinds, part.tool_name) ||
				resolved.has(part.tool_call_id)
			)
				return [];
			return [
				{
					toolCallId: part.tool_call_id,
					messageId: entry.entry_id!,
					contentIndex,
					key: JSON.stringify([entry.entry_id, contentIndex, part.tool_call_id]),
					question:
						entry.stop_reason === 'length'
							? undefined
							: parseQuestionInput(
									part.tool_name as QuestionTool,
									part.arguments,
									part.tool_call_id
								)
				}
			];
		});
	}
	return [];
}

export function pendingQuestionOf(
	entries: Entry[],
	streamingEntryId?: string
): PendingQuestion | undefined {
	return questionCallsOf(entries, streamingEntryId).find(
		(call): call is PendingQuestion => call.question !== undefined
	);
}

export function needsContinuation(entries: Entry[]): boolean {
	let end = entries.length - 1;
	while (end >= 0) {
		const entry = entries[end]!;
		if (
			entry.kind !== 'marker' ||
			!['side-question', 'side-question-told'].includes(entry.marker_type)
		)
			break;
		end--;
	}
	const last = entries[end];
	if (last?.kind !== 'tool_result') return false;
	const details = asObject(last.details);
	if (details?.dismissed === true || (last.is_error && details?.question_recovery === true))
		return false;
	const resolved = new Set<string>();
	for (let i = end; i >= 0; i--) {
		const entry = entries[i]!;
		if (entry.kind === 'tool_result') {
			resolved.add(entry.tool_call_id);
			continue;
		}
		if (entry.kind !== 'assistant') return false;
		const calls = entry.parts.filter((part): part is ToolCallPart => part.type === 'tool_call');
		return calls.length > 0 && calls.every((part) => resolved.has(part.tool_call_id));
	}
	return false;
}
