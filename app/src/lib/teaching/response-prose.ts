import type { Entry, ToolResult } from '#lib/api/client.js';
import { isJobKind, type JobKind } from '#lib/jobs/jobs.js';
import { CONCLUDE_TOOL, PROBLEM_TOOL } from '#lib/practice/state.js';
import { parseJson } from '#lib/questions/question-core.js';
import { asObject } from '#lib/questions/question-input.js';
import { isBuiltInTool } from './built-in-tools.js';
import { sendToUserText } from './delivery.js';

type Assistant = Extract<Entry, { kind: 'assistant' }>;
export type ResponseItem =
	| { kind: 'text'; text: string }
	| { kind: 'probe'; args: unknown; result?: ToolResult }
	| { kind: 'problem'; statement: string }
	| { kind: 'conclude'; args: unknown; toolCallId: string }
	| { kind: 'prepared-session'; result: ToolResult }
	| { kind: 'tool-retry' }
	| { kind: 'image'; result?: ToolResult }
	| { kind: 'job'; jobKind: JobKind; toolCallId: string }
	| { kind: 'tool'; name: string; args: unknown; result?: ToolResult; stopped: boolean };

export function responseProse(
	entry: Assistant,
	results: Map<string, ToolResult> | undefined,
	streaming: boolean
) {
	const items: ResponseItem[] = [];
	let text = '';
	function flushText() {
		if (text) items.push({ kind: 'text', text });
		text = '';
	}
	for (const part of entry.parts) {
		if (part.type === 'text') text += part.text;
		if (part.type !== 'tool_call') continue;
		const result = results?.get(part.tool_call_id);
		if (!isBuiltInTool(part.tool_name)) {
			flushText();
			const stopped = entry.stop_reason === 'aborted' || entry.stop_reason === 'error';
			items.push({ kind: 'tool', name: part.tool_name, args: part.arguments, result, stopped });
		} else if (result?.is_error) {
			if (result.text !== 'Operation aborted' && entry.stop_reason !== 'aborted') {
				flushText();
				items.push({ kind: 'tool-retry' });
			}
		} else if (part.tool_name === 'show_image') {
			flushText();
			items.push({ kind: 'image', result });
		} else if (result && isJobKind(part.tool_name)) {
			flushText();
			items.push({ kind: 'job', jobKind: part.tool_name, toolCallId: part.tool_call_id });
		} else if (result && part.tool_name === PROBLEM_TOOL) {
			flushText();
			const statement = asObject(parseJson(part.arguments))?.statement;
			items.push({ kind: 'problem', statement: typeof statement === 'string' ? statement : '' });
		} else if (result && part.tool_name === CONCLUDE_TOOL) {
			flushText();
			items.push({ kind: 'conclude', args: part.arguments, toolCallId: part.tool_call_id });
		} else if (part.tool_name === 'probe_done') {
			flushText();
			items.push({ kind: 'probe', args: part.arguments, result });
		} else if (result && part.tool_name === 'prepare_session') {
			flushText();
			items.push({ kind: 'prepared-session', result });
		} else if (
			part.tool_name === 'send_to_user' &&
			entry.stop_reason !== 'aborted' &&
			entry.stop_reason !== 'error'
		) {
			flushText();
			const delivered = sendToUserText(part.arguments, streaming);
			if (delivered) items.push({ kind: 'text', text: delivered });
		}
	}
	flushText();
	return items;
}
