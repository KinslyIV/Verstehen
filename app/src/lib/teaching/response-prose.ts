import type { Entry, ToolResult } from '#lib/api/client.js';
import { isJobKind, type JobKind } from '#lib/jobs/jobs.js';
import { sendToUserText } from './delivery.js';

type Assistant = Extract<Entry, { kind: 'assistant' }>;
type ResponseItem =
	| { kind: 'text'; text: string }
	| { kind: 'probe'; args: unknown; result?: ToolResult }
	| { kind: 'tool-retry' }
	| { kind: 'image'; result?: ToolResult }
	| { kind: 'job'; jobKind: JobKind; toolCallId: string };

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
		if (result?.is_error) {
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
		} else if (part.tool_name === 'probe_done') {
			flushText();
			items.push({ kind: 'probe', args: part.arguments, result });
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
