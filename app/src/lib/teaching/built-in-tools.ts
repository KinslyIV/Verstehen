/** Every tool name the app itself offers; the backend's `plugins/reserved.py` holds the same list. */
const BUILT_IN_TOOLS = new Set([
	'probe',
	'recall',
	'quiz',
	'explain',
	'ask_user_question',
	'probe_done',
	'send_to_user',
	'plan_init',
	'show_image',
	'problem',
	'conclude',
	'research',
	'demo',
	'visual',
	'pdf',
	'read',
	'ls',
	'find',
	'grep',
	'list_sessions',
	'list_propositions',
	'list_prompts',
	'read_prompt',
	'read_settings',
	'list_sessions_and_folders',
	'list_graph_nodes',
	'read_graph_node',
	'read_session',
	'read_app_guide',
	'prepare_session'
]);

export function isBuiltInTool(name: string) {
	return BUILT_IN_TOOLS.has(name);
}
