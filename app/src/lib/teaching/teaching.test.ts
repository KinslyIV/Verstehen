import { expect, test } from 'vitest';
import type { Entry } from '#lib/api/client.js';
import { phaseTimeline, teachStepIndex } from './phases.js';
import { derivePlanStatuses, type Plan } from './plan.js';
import { layoutPlan } from './plan-layout.js';
import { sendToUserText } from './delivery.js';
import { responseProse } from './response-prose.js';
import {
	composeAddFolder,
	composeFileRestriction,
	composeRemoveFolder,
	isFileAccessFolder,
	openFileAccess
} from './file-access.js';

function call(tool: string, args: unknown, id = tool): Extract<Entry, { kind: 'assistant' }> {
	return {
		kind: 'assistant',
		stop_reason: 'stop',
		parts: [
			{
				type: 'tool_call',
				tool_call_id: id,
				tool_name: tool,
				arguments: args
			}
		]
	};
}

const result = {
	kind: 'tool_result',
	tool_call_id: 'probe_done',
	tool_name: 'probe_done',
	is_error: false,
	text: 'Assessment recorded.',
	details: { ok: true }
} as const;

test('phase_timeline_advances_on_the_successful_probe_and_at_the_tagged_provider_step', () => {
	const entries: Entry[] = [
		call('probe_done', {}),
		{ ...result, details: { ok: false } },
		call('quiz', { nodeId: 'before-assessment' }),
		call('probe_done', {}),
		result,
		{ kind: 'marker', marker_type: 'probe-handoff', content: 'Plan', display: true },
		{ kind: 'assistant', stop_reason: 'stop', parts: [{ type: 'text', text: 'The plan.' }] },
		call('quiz', { nodeId: '' }),
		call('explain', JSON.stringify({ nodeId: 'slope' })),
		call('quiz', { nodeId: 'secant' })
	];
	expect(phaseTimeline(entries)).toEqual({
		timeline: [
			'probe',
			'probe',
			'probe',
			'probe',
			'plan',
			'plan',
			'plan',
			'plan',
			'teach',
			'teach'
		],
		teachAt: 8,
		owed: false
	});
	expect(teachStepIndex(entries.slice(6))).toBe(2);
	expect(teachStepIndex(entries.slice(8))).toBe(0);
	expect(teachStepIndex(entries.slice(6, 8))).toBe(-1);
	expect(phaseTimeline([{ ...call('probe_done', {}), stop_reason: 'aborted' }, result]).owed).toBe(
		false
	);
	expect(
		phaseTimeline([call('probe_done', {}), result, { kind: 'user', text: 'My goal' }]).owed
	).toBe(false);
});

const plan: Plan = {
	nodes: [
		{ id: 'slope', title: 'Compare slopes' },
		{ id: 'secant', title: 'Secant' },
		{ id: 'limit', title: 'Bring the two points together until their distance approaches zero' },
		{ id: 'derivative', title: 'Derivative' }
	],
	edges: [
		{ from: 'slope', to: 'secant' },
		{ from: 'slope', to: 'limit' },
		{ from: 'secant', to: 'derivative' },
		{ from: 'limit', to: 'derivative' }
	]
};

test('plan_position_uses_tagged_calls_ignores_removed_nodes_and_moves_back_to_visited_nodes', () => {
	const entries = [
		call('quiz', { nodeId: 'slope' }),
		call('quiz', { nodeId: 'slope' }),
		call('explain', { nodeId: 'secant' }),
		call('quiz', { nodeId: 'removed' }),
		call('quiz', { nodeId: 'slope' })
	];
	expect(Object.fromEntries(derivePlanStatuses(plan, []))).toEqual({
		slope: 'upcoming',
		secant: 'upcoming',
		limit: 'upcoming',
		derivative: 'upcoming'
	});
	expect(Object.fromEntries(derivePlanStatuses(plan, entries))).toEqual({
		slope: 'current',
		secant: 'visited',
		limit: 'upcoming',
		derivative: 'upcoming'
	});
	expect(derivePlanStatuses(plan, entries.slice(0, 4)).get('secant')).toBe('current');
});

test('plan_layout_places_every_node_and_routes_every_dependency', () => {
	const layout = layoutPlan(plan);
	expect(layout.nodes.map(({ id }) => id)).toEqual(plan.nodes.map(({ id }) => id));
	expect(layout.nodes.every(({ x, y }) => Number.isFinite(x) && Number.isFinite(y))).toBe(true);
	const [slope, secant, limit, derivative] = layout.nodes;
	expect(slope!.y).toBeLessThan(secant!.y);
	expect(limit!.y).toBeLessThan(derivative!.y);
	expect(limit!.lines.join(' ')).toBe(plan.nodes[2]!.title);
	expect(layout.paths.map(({ from, to }) => ({ from, to }))).toEqual(plan.edges);
	expect(layout.paths.every(({ path }) => path.startsWith('M') && path.includes('C'))).toBe(true);
});

test('send_to_user_reads_complete_and_partial_arguments_with_json_escapes', () => {
	expect(sendToUserText({ message: 'Hi' }, false)).toBe('Hi');
	expect(sendToUserText('{"message":"Hello \\"world\\"\\nSo far', true)).toBe(
		'Hello "world"\nSo far'
	);
	expect(sendToUserText('{"message":"Hello \\u20', true)).toBe('Hello ');
	expect(sendToUserText('{"message":"Hello', false)).toBeUndefined();
	expect(sendToUserText('{"message":42}', true)).toBeUndefined();
	expect(sendToUserText({ message: '   ' }, false)).toBeUndefined();
});

test('failed_send_to_user_shows_the_tool_error_in_place_of_its_prose', () => {
	const entry = call('send_to_user', { message: 'Preview' }, 'send');
	const error = {
		...result,
		tool_name: 'send_to_user',
		tool_call_id: 'send',
		text: 'Invalid',
		is_error: true
	};
	expect(responseProse(entry, new Map([['send', error]]), false)).toEqual([
		{ kind: 'send-error', text: 'Invalid' }
	]);
	expect(responseProse({ ...entry, stop_reason: 'aborted' }, undefined, false)).toEqual([]);
});

test('file_access_composes_the_switch_and_folder_list_independently', () => {
	expect(isFileAccessFolder('relative')).toBe(false);
	expect(isFileAccessFolder('/tmp/\0')).toBe(false);
	for (const path of ['~', '~/Notes', '/tmp/notes', 'D:\\notes', '\\\\server\\notes']) {
		expect(isFileAccessFolder(path)).toBe(true);
	}
	const withFolder = composeAddFolder(openFileAccess, ' ~/Notes  ');
	expect(withFolder).toEqual({ restricted: false, folders: ['~/Notes'] });
	expect(composeAddFolder(withFolder, '~/Notes')).toBe(withFolder);
	expect(composeAddFolder(withFolder, 'relative')).toBe(withFolder);
	const restricted = composeFileRestriction(withFolder, true);
	expect(restricted).toEqual({ restricted: true, folders: ['~/Notes'] });
	expect(composeRemoveFolder(restricted, '~/Notes')).toEqual({ restricted: true, folders: [] });
});
