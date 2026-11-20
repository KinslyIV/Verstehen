import type { Entry } from '#lib/api/client.js';

export const probeArguments = {
	question: 'Which number is even?',
	options: [
		{ label: 'Two', value: 'two' },
		{ label: 'Three', value: 'three' }
	],
	correctAnswer: 'two',
	explanation: 'Two is divisible by two.'
};

export function questionBatch(...ids: string[]): Extract<Entry, { kind: 'assistant' }> {
	return {
		kind: 'assistant',
		entry_id: 'a',
		stop_reason: 'stop',
		parts: ids.map((id) => ({
			type: 'tool_call',
			tool_call_id: id,
			tool_name: 'probe',
			arguments: probeArguments
		}))
	};
}

export function questionResult(
	id: string,
	details: Extract<Entry, { kind: 'tool_result' }>['details'] = {}
): Extract<Entry, { kind: 'tool_result' }> {
	return {
		kind: 'tool_result',
		entry_id: `result-${id}`,
		tool_call_id: id,
		tool_name: 'probe',
		text: '{}',
		is_error: false,
		details
	};
}
