import type { Entry, ToolResult } from '#lib/api/client.js';
import { parseJson } from '#lib/questions/question-core.js';
import { asObject } from '#lib/questions/question-input.js';
import { sendToUserText } from './delivery.js';

type Assistant = Extract<Entry, { kind: 'assistant' }>;
type ResponseItem =
	| { kind: 'text'; text: string }
	| { kind: 'probe'; args: unknown; result?: ToolResult }
	| { kind: 'send-error'; text: string };

function toolErrorText(text: string): string {
	const diagnostics = parseJson(text);
	if (!Array.isArray(diagnostics) || !diagnostics.length) return text;
	const messages = diagnostics.map((diagnostic) => asObject(diagnostic)?.msg);
	return messages.every((message) => typeof message === 'string') ? messages.join('\n') : text;
}

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
		if (
			part.type !== 'tool_call' ||
			(part.tool_name !== 'probe_done' && part.tool_name !== 'send_to_user')
		)
			continue;
		const result = results?.get(part.tool_call_id);
		if (part.tool_name === 'probe_done') {
			flushText();
			items.push({ kind: 'probe', args: part.arguments, result });
		} else if (entry.stop_reason !== 'aborted' && entry.stop_reason !== 'error') {
			flushText();
			if (result?.is_error) items.push({ kind: 'send-error', text: toolErrorText(result.text) });
			else {
				const delivered = sendToUserText(part.arguments, streaming);
				if (delivered) items.push({ kind: 'text', text: delivered });
			}
		}
	}
	flushText();
	return items;
}
