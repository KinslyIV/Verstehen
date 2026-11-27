import { expect, test } from 'vitest';
import type { Entry, ToolResult } from '#lib/api/client.js';
import { workingStatus } from './working-status.js';

const noResults = new Map<string, Map<string, ToolResult>>();

test('workingStatus_is_null_when_idle', () => {
	expect(workingStatus([], noResults, undefined, false)).toBeNull();
});

test('workingStatus_shows_thinking_while_waiting_for_first_assistant_content', () => {
	const user: Entry = { kind: 'user', entry_id: 'u1', text: 'Hi' };
	expect(workingStatus([user], noResults, undefined, true)).toBe('Thinking…');

	const emptyAssistant: Entry = {
		kind: 'assistant',
		entry_id: 'a1',
		stop_reason: 'stop',
		parts: []
	};
	expect(workingStatus([user, emptyAssistant], noResults, 'a1', true)).toBe('Thinking…');
});

test('workingStatus_hides_when_reasoning_or_visible_prose_is_streaming', () => {
	const thinkingEntry: Entry = {
		kind: 'assistant',
		entry_id: 'a1',
		stop_reason: 'stop',
		parts: [{ type: 'thinking', thinking: 'Let me think', redacted: false }]
	};
	expect(workingStatus([thinkingEntry], noResults, 'a1', true)).toBeNull();

	const textEntry: Entry = {
		kind: 'assistant',
		entry_id: 'a2',
		stop_reason: 'stop',
		parts: [{ type: 'text', text: 'Here is' }]
	};
	expect(workingStatus([textEntry], noResults, 'a2', true)).toBeNull();

	const sendEntry: Entry = {
		kind: 'assistant',
		entry_id: 'a3',
		stop_reason: 'stop',
		parts: [
			{
				type: 'tool_call',
				tool_call_id: 'call_send',
				tool_name: 'send_to_user',
				arguments: '{"message":"Hello'
			}
		]
	};
	expect(workingStatus([sendEntry], noResults, 'a3', true)).toBeNull();
});

test('workingStatus_maps_pending_builtin_tools_and_ignores_plugin_tools', () => {
	const builtin: Entry = {
		kind: 'assistant',
		entry_id: 'a1',
		stop_reason: 'stop',
		parts: [
			{ type: 'tool_call', tool_call_id: 'c1', tool_name: 'list_prompts', arguments: {} },
			{ type: 'tool_call', tool_call_id: 'c2', tool_name: 'list_graph_nodes', arguments: {} }
		]
	};
	const partial = new Map<string, Map<string, ToolResult>>([
		[
			'a1',
			new Map([
				[
					'c1',
					{
						kind: 'tool_result',
						entry_id: 'r1',
						tool_call_id: 'c1',
						tool_name: 'list_prompts',
						text: 'ok',
						is_error: false
					}
				]
			])
		]
	]);
	expect(workingStatus([builtin], partial, 'a1', true)).toBe('Reading knowledge graph…');

	const plugin: Entry = {
		kind: 'assistant',
		entry_id: 'a2',
		stop_reason: 'stop',
		parts: [{ type: 'tool_call', tool_call_id: 'p1', tool_name: 'hello_greet', arguments: {} }]
	};
	expect(workingStatus([plugin], noResults, 'a2', true)).toBeNull();

	const builtInBeforePlugin: Entry = {
		kind: 'assistant',
		entry_id: 'a3',
		stop_reason: 'stop',
		parts: [
			{ type: 'tool_call', tool_call_id: 'c1', tool_name: 'list_graph_nodes', arguments: {} },
			{ type: 'tool_call', tool_call_id: 'p1', tool_name: 'hello_greet', arguments: {} }
		]
	};
	expect(workingStatus([builtInBeforePlugin], noResults, 'a3', true)).toBe(
		'Reading knowledge graph…'
	);

	const pluginBeforeBuiltIn: Entry = {
		kind: 'assistant',
		entry_id: 'a4',
		stop_reason: 'stop',
		parts: [
			{ type: 'tool_call', tool_call_id: 'p1', tool_name: 'hello_greet', arguments: {} },
			{ type: 'tool_call', tool_call_id: 'c1', tool_name: 'list_graph_nodes', arguments: {} }
		]
	};
	expect(workingStatus([pluginBeforeBuiltIn], noResults, 'a4', true)).toBe(
		'Reading knowledge graph…'
	);

	const sendWithBuiltIn: Entry = {
		kind: 'assistant',
		entry_id: 'a5',
		stop_reason: 'stop',
		parts: [
			{
				type: 'tool_call',
				tool_call_id: 's1',
				tool_name: 'send_to_user',
				arguments: '{"message":"Visible prose'
			},
			{ type: 'tool_call', tool_call_id: 'c1', tool_name: 'list_graph_nodes', arguments: {} }
		]
	};
	expect(workingStatus([sendWithBuiltIn], noResults, 'a5', true)).toBeNull();

	expect(workingStatus([builtInBeforePlugin], noResults, 'a3', true, ['c1'])).toBeNull();

	const twoBuiltIns: Entry = {
		kind: 'assistant',
		entry_id: 'a6',
		stop_reason: 'stop',
		parts: [
			{ type: 'tool_call', tool_call_id: 'b1', tool_name: 'list_prompts', arguments: {} },
			{ type: 'tool_call', tool_call_id: 'b2', tool_name: 'list_graph_nodes', arguments: {} }
		]
	};
	expect(workingStatus([twoBuiltIns], noResults, 'a6', true, ['b2'])).toBe('Checking prompts…');
});

test('workingStatus_shows_working_between_completed_steps', () => {
	const settledStep: Entry = {
		kind: 'assistant',
		entry_id: 'a1',
		stop_reason: 'stop',
		parts: [{ type: 'text', text: 'Step 1' }]
	};
	expect(workingStatus([settledStep], noResults, undefined, true)).toBe('Working…');
});
