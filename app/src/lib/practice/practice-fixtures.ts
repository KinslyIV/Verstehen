import type { Entry } from '#lib/api/client.js';

type Assistant = Extract<Entry, { kind: 'assistant' }>;
type Result = Extract<Entry, { kind: 'tool_result' }>;

export const problemArguments = {
	statement: 'Differentiate $x^2$.',
	mode: 'recall',
	target: ['n1'],
	modelSolution: 'The derivative is $2x$.'
};

export const concludeArguments = {
	outcome: 'solved',
	verdict: 'Credited the power rule.',
	rung: null,
	missClass: null,
	retest: false
};

export const call = (id: string, name: string, args: unknown = {}): Assistant => ({
	kind: 'assistant',
	entry_id: `a-${id}`,
	stop_reason: 'stop',
	parts: [{ type: 'tool_call', tool_call_id: id, tool_name: name, arguments: args as never }]
});

export const ack = (id: string, name: string, patch: Partial<Result> = {}): Result => ({
	kind: 'tool_result',
	entry_id: `r-${id}`,
	tool_call_id: id,
	tool_name: name,
	text: 'ok',
	is_error: false,
	...patch
});

export const pose = (id = 'p1'): [Assistant, Result] => [
	call(id, 'problem', problemArguments),
	ack(id, 'problem')
];
export const conclude = (id = 'c1') => [
	call(id, 'conclude', concludeArguments),
	ack(id, 'conclude')
];
export const dismissed = (id = 'p1'): Entry => ({
	kind: 'marker',
	marker_type: 'problem-dismissed',
	content: '',
	display: true,
	details: { problem_call_id: id }
});
