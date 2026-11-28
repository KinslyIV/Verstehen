import type { Entry, ToolResult } from '#lib/api/client.js';
import { isBuiltInTool } from '#lib/teaching/built-in-tools.js';
import { sendToUserText } from '#lib/teaching/delivery.js';

const TOOL_LABELS: Record<string, string> = {
	list_prompts: 'Checking prompts…',
	read_prompt: 'Checking prompts…',
	read_settings: 'Checking settings…',
	list_sessions_and_folders: 'Reading sessions…',
	list_sessions: 'Reading sessions…',
	read_session: 'Reading sessions…',
	list_graph_nodes: 'Reading knowledge graph…',
	read_graph_node: 'Reading knowledge graph…',
	list_propositions: 'Reading knowledge graph…',
	read_app_guide: 'Checking guide…',
	prepare_session: 'Preparing session…',
	read: 'Reading file…',
	ls: 'Searching files…',
	find: 'Searching files…',
	grep: 'Searching files…',
	plan_init: 'Building lesson plan…',
	probe_done: 'Reviewing what you know…',
	probe: 'Preparing question…',
	recall: 'Preparing question…',
	quiz: 'Preparing question…',
	explain: 'Preparing question…',
	ask_user_question: 'Preparing question…',
	problem: 'Preparing problem…',
	conclude: 'Wrapping up problem…',
	show_image: 'Preparing image…',
	research: 'Starting research…',
	pdf: 'Reading PDF…',
	demo: 'Building demo…',
	visual: 'Creating visual…',
	send_to_user: 'Writing response…'
};

export function toolActivityLabel(toolName: string): string {
	return TOOL_LABELS[toolName] ?? 'Working…';
}

/** Live status label when a turn is working without visible streaming prose or a Reasoning row. */
export function workingStatus(
	entries: Entry[],
	results: Map<string, Map<string, ToolResult>>,
	streamingEntryId: string | undefined,
	busy: boolean,
	completedToolCallIds: readonly string[] = []
): string | null {
	if (!busy) return null;
	const tail = entries.at(-1);
	if (!tail || tail.kind !== 'assistant') return 'Thinking…';
	const tailResults = tail.entry_id ? results.get(tail.entry_id) : undefined;
	const streaming = tail.entry_id === streamingEntryId;
	const completed =
		streaming && completedToolCallIds.length ? new Set(completedToolCallIds) : undefined;
	const pendingCalls = tail.parts.filter(
		(part): part is Extract<typeof part, { type: 'tool_call' }> =>
			part.type === 'tool_call' &&
			!tailResults?.has(part.tool_call_id) &&
			!completed?.has(part.tool_call_id)
	);
	if (pendingCalls.length > 0) {
		const otherBuiltIn = pendingCalls
			.filter((part) => part.tool_name !== 'send_to_user' && isBuiltInTool(part.tool_name))
			.at(-1);
		if (otherBuiltIn) return toolActivityLabel(otherBuiltIn.tool_name);
		if (
			pendingCalls.some(
				(part) =>
					part.tool_name === 'send_to_user' && streaming && sendToUserText(part.arguments, true)
			)
		) {
			return null;
		}
		const activeBuiltIn = pendingCalls.filter((part) => isBuiltInTool(part.tool_name)).at(-1);
		if (activeBuiltIn) return toolActivityLabel(activeBuiltIn.tool_name);
		return null;
	}
	if (!streaming) return 'Working…';
	if (tail.parts.length === 0) return 'Thinking…';
	const lastPart = tail.parts.at(-1);
	if (lastPart?.type === 'text' && lastPart.text.trim().length > 0) return null;
	if (lastPart?.type === 'thinking' && lastPart.thinking.length > 0) return null;
	return 'Thinking…';
}
