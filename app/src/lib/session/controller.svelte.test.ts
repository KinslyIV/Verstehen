import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { SessionController } from './controller.svelte';
import * as api from '#lib/api/client.js';
import { questionBatch, questionResult } from '#lib/questions/question-fixtures.js';
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	dismissQuestion: vi.fn(),
	getJobs: vi.fn(),
	getExtractionStatus: async () => [],
	getSettings: async () => ({}),
	steerSession: vi.fn(),
	setArtifactView: vi.fn(),
	getSession: vi.fn(),
	postInput: vi.fn(),
	streamTurn: vi.fn()
}));
const record = (entries: api.Entry[] = [], busy = false): api.SessionDetail => ({
	side_segments: { by_entry: {}, entry_points: {}, current: null },
	id: 'one',
	title: 'Lesson',
	kind: 'teach',
	entries,
	turn_in_flight: busy,
	turn_error: null
});
let controller: SessionController;
beforeEach(() => {
	vi.mocked(api.getSession).mockReset().mockResolvedValue(record());
	vi.mocked(api.getJobs).mockReset().mockResolvedValue({ jobs: [], turn_in_flight: false });
	vi.mocked(api.steerSession).mockReset().mockResolvedValue();
	vi.mocked(api.setArtifactView).mockReset().mockResolvedValue();
	vi.mocked(api.dismissQuestion).mockReset().mockResolvedValue(false);
	vi.mocked(api.postInput).mockReset().mockResolvedValue();
	vi.mocked(api.streamTurn).mockReset().mockResolvedValue(true);
	controller = new SessionController('one', 1, 20);
});
afterEach(() => controller.dispose());
test('refused_send_restores_draft_and_opens_setup', async () => {
	await controller.load();
	controller.draft = 'Algebra';
	vi.mocked(api.postInput).mockRejectedValue(
		new api.ApiError(503, 'models_not_configured', 'missing')
	);
	await controller.send();
	expect(controller.draft).toBe('Algebra');
	expect(controller.setupOpen).toBe(true);
	expect(controller.busy).toBe(false);
	expect(controller.entries).toEqual([]);
});
test('saved_entries_merge_only_by_append_and_live_updates_replace_their_slot', async () => {
	const user: api.Entry = { kind: 'user', entry_id: 'u', text: 'Why?' };
	vi.mocked(api.getSession).mockResolvedValue(record([user], true));
	vi.mocked(api.streamTurn).mockImplementation(async (_, receive) => {
		for (const text of ['A', 'Answer'])
			receive({
				type: 'message_update',
				message: {
					kind: 'assistant',
					entry_id: 'a',
					parts: [{ type: 'text', text }],
					stop_reason: 'stop'
				}
			});
		expect(controller.entries).toHaveLength(2);
		controller.adoptRecord(record([]));
		expect(controller.entries[0]).toEqual(user);
		vi.mocked(api.getSession).mockResolvedValue(record([user, controller.entries[1]]));
		return true;
	});
	await controller.load();
	await expect.poll(() => controller.busy).toBe(false);
	expect(controller.entries).toHaveLength(2);
});
test('early_stream_end_recovers_once_without_resending_input', async () => {
	await controller.load();
	vi.mocked(api.getSession).mockResolvedValue(record([], true));
	vi.mocked(api.streamTurn).mockResolvedValue(false);
	await controller.attach();
	expect(api.streamTurn).toHaveBeenCalledTimes(2);
	expect(api.postInput).not.toHaveBeenCalled();
	expect(controller.error).toBe('The connection dropped before the turn completed.');
});
test('conflict_polls_and_retries_the_same_input', async () => {
	controller.dispose();
	controller = new SessionController('one', 1, 5_000);
	await controller.load();
	controller.draft = 'Why?';
	vi.mocked(api.postInput)
		.mockRejectedValueOnce(new api.ApiError(409, undefined, 'busy'))
		.mockResolvedValue();
	await controller.send();
	expect(api.postInput).toHaveBeenCalledTimes(2);
	expect(vi.mocked(api.postInput).mock.calls[0][1]).toEqual(
		vi.mocked(api.postInput).mock.calls[1][1]
	);
});
test('retry_preserves_todays_unsent_draft', async () => {
	await controller.load();
	controller.draft = 'Unsent';
	await controller.send('retry');
	expect(controller.draft).toBe('Unsent');
	expect(api.postInput).toHaveBeenCalledWith('one', { type: 'retry' }, expect.any(AbortSignal));
});

test('conflict_wait_has_a_bound_and_restores_the_draft', async () => {
	await controller.load();
	controller.draft = 'Keep me';
	vi.mocked(api.postInput).mockRejectedValue(new api.ApiError(409, undefined, 'busy'));
	vi.mocked(api.getSession).mockResolvedValue(record([], true));
	await controller.send();
	expect(api.postInput).toHaveBeenCalledOnce();
	expect(controller.draft).toBe('Keep me');
	expect(controller.error).toBe('busy');
	expect(controller.busy).toBe(false);
});
test('saved_provider_failure_is_visible_after_server_restart', async () => {
	vi.mocked(api.getSession).mockResolvedValue(
		record([
			{
				kind: 'assistant',
				entry_id: 'a',
				parts: [],
				stop_reason: 'error',
				error_text: 'Provider failed'
			}
		])
	);
	await controller.load();
	expect(controller.error).toBe('Provider failed');
});

test('unusable_model_opens_menu_with_reason_and_keeps_the_draft', async () => {
	await controller.load();
	controller.draft = 'Keep me';
	vi.mocked(api.postInput).mockRejectedValue(
		new api.ApiError(503, 'model_unavailable', 'unavailable', 'Sign in again.')
	);
	await controller.send();
	expect(controller.draft).toBe('Keep me');
	expect(controller.modelMenuOpen).toBe(true);
	expect(controller.notice).toBe('Sign in again.');
	expect(controller.error).toBeNull();
	expect(controller.entries).toEqual([]);
});

test('mount_continues_an_answer_saved_without_its_reaction_once', async () => {
	const entries = [questionBatch('one'), questionResult('one')];
	vi.mocked(api.getSession).mockResolvedValue(record(entries));
	await controller.load();
	expect(api.postInput).toHaveBeenCalledExactlyOnceWith(
		'one',
		{ type: 'continue' },
		expect.any(AbortSignal)
	);
});

test('sync_does_not_automatically_retry_a_failed_continuation', async () => {
	const entries = [questionBatch('one'), questionResult('one')];
	vi.mocked(api.getSession).mockResolvedValue(record(entries));
	vi.mocked(api.postInput).mockRejectedValue(new Error('Network unavailable'));
	await controller.load();
	await controller.synchronize();
	expect(api.postInput).toHaveBeenCalledOnce();
});

test('a_turn_merges_all_responses_and_keeps_their_saved_results_in_order', async () => {
	const first = questionBatch('invalid');
	const last = { ...questionBatch('replacement'), entry_id: 'replacement-message' };
	const invalid = { ...questionResult('invalid'), is_error: true };
	vi.mocked(api.getSession).mockResolvedValue(record([], true));
	vi.mocked(api.streamTurn).mockImplementation(async (_, receive) => {
		receive({ type: 'message_start', message: { ...first, parts: [] } });
		receive({ type: 'message_end', message: first });
		receive({ type: 'message_start', message: { ...last, parts: [] } });
		expect(controller.entries).toHaveLength(2);
		expect(controller.streamingEntryId).toBe(last.entry_id);
		receive({ type: 'message_end', message: last });
		vi.mocked(api.getSession).mockResolvedValue(record([first, invalid, last]));
		return true;
	});
	await controller.load();
	await expect.poll(() => controller.busy).toBe(false);
	expect(controller.entries).toEqual([first, invalid, last]);
	expect(controller.pendingQuestion?.toolCallId).toBe('replacement');
});

const probeDone: api.Entry[] = [
	{
		kind: 'assistant',
		entry_id: 'assess',
		stop_reason: 'stop',
		parts: [{ type: 'tool_call', tool_call_id: 'probe', tool_name: 'probe_done', arguments: {} }]
	},
	{
		kind: 'tool_result',
		entry_id: 'ack',
		tool_call_id: 'probe',
		tool_name: 'probe_done',
		is_error: false,
		text: 'Recorded',
		details: { ok: true }
	}
];

test('mount_sends_a_saved_owed_handoff_once_before_continue', async () => {
	vi.mocked(api.getSession).mockResolvedValue(record(probeDone));
	await controller.load();
	expect(api.postInput).toHaveBeenCalledExactlyOnceWith(
		'one',
		{ type: 'handoff' },
		expect.any(AbortSignal)
	);
});

test('sync_sends_an_owed_handoff_when_the_turn_and_question_clear', async () => {
	await controller.load();
	vi.mocked(api.getSession).mockResolvedValueOnce({ ...record(probeDone), turn_error: 'Failed' });
	await controller.synchronize();
	vi.mocked(api.getSession).mockResolvedValueOnce(record([...probeDone, questionBatch('open')]));
	await controller.synchronize();
	expect(api.postInput).not.toHaveBeenCalled();
	vi.mocked(api.getSession).mockResolvedValue(
		record([
			...probeDone,
			questionBatch('open'),
			{ ...questionResult('open'), details: { dismissed: true } }
		])
	);
	await controller.synchronize();
	expect(api.postInput).toHaveBeenCalledExactlyOnceWith(
		'one',
		{ type: 'handoff' },
		expect.any(AbortSignal)
	);
});

test('sync_recovers_an_owed_handoff_after_a_transient_input_error', async () => {
	vi.mocked(api.getSession).mockResolvedValue(record(probeDone));
	vi.mocked(api.postInput).mockRejectedValueOnce(new Error('Connection interrupted'));
	await controller.load();
	expect(controller.error).toBe('Connection interrupted');
	await controller.synchronize();
	expect(controller.error).toBeNull();
	expect(vi.mocked(api.postInput).mock.calls.map(([, input]) => input)).toEqual([
		{ type: 'handoff' },
		{ type: 'handoff' }
	]);
});

test('mount_attaches_to_a_running_turn_then_follows_the_server_started_handoff', async () => {
	const marker = {
		kind: 'marker',
		entry_id: 'handoff',
		marker_type: 'probe-handoff',
		content: 'Plan',
		display: true
	} as const;
	vi.mocked(api.getSession)
		.mockResolvedValueOnce(record(probeDone, true))
		.mockResolvedValueOnce(record([...probeDone, marker], true))
		.mockResolvedValueOnce(record([...probeDone, marker]));
	await controller.load();
	await expect.poll(() => controller.busy).toBe(false);
	expect(api.streamTurn).toHaveBeenCalledTimes(2);
	expect(api.postInput).not.toHaveBeenCalled();
});

test('saved_plan_is_baseline_and_each_new_successful_plan_opens_only_once', async () => {
	const onPlan = vi.fn();
	controller.onNewPlan = onPlan;
	const planResult = (id: string, title: string): api.ToolResult => ({
		kind: 'tool_result',
		entry_id: id,
		tool_call_id: 'plan',
		tool_name: 'plan_init',
		is_error: false,
		text: 'Plan',
		details: { ok: true, tree: { nodes: [{ id: 'slope', title }], edges: [], version: 1 } }
	});
	const first = planResult('first', 'First');
	controller.adoptRecord(record([first]));
	expect(onPlan).not.toHaveBeenCalled();
	expect(controller.plan?.nodes[0]?.title).toBe('First');

	const next = planResult('second', 'Revised');
	vi.mocked(api.getSession).mockResolvedValue(record([first, next]));
	vi.mocked(api.streamTurn).mockImplementation(async (_, receive) => {
		receive({
			type: 'message_end',
			message: {
				kind: 'assistant',
				entry_id: 'rewrite',
				stop_reason: 'stop',
				parts: []
			},
			results: [next]
		});
		expect(controller.plan?.nodes[0]?.title).toBe('Revised');
		expect(onPlan).toHaveBeenCalledOnce();
		return true;
	});
	await controller.attach();
	expect(onPlan).toHaveBeenCalledOnce();
});

const compacting = (entries: api.Entry[]): api.SessionDetail => ({
	...record(entries),
	compacting: true
});

test('submissions_wait_while_the_session_compacts', async () => {
	const entries = [questionBatch('one')];
	vi.mocked(api.getSession).mockResolvedValue(compacting(entries));
	await controller.load();
	controller.draft = 'Hello';
	await controller.send();
	await controller.send('retry');
	await controller.answerQuestion(
		controller.pendingQuestion!,
		{ kind: 'quiz' } as never,
		{} as never
	);
	await controller.retryQuestion({ toolCallId: 'one', messageId: 'a', contentIndex: 0, key: 'k' });
	expect(controller.compacting).toBe(true);
	expect(api.postInput).not.toHaveBeenCalled();
	expect(controller.draft).toBe('Hello');
});

test('a_saved_answer_continues_only_after_compaction_ends', async () => {
	const entries = [questionBatch('one'), questionResult('one')];
	vi.mocked(api.getSession).mockResolvedValue(compacting(entries));
	await controller.load();
	expect(api.postInput).not.toHaveBeenCalled();
	vi.mocked(api.getSession).mockResolvedValue(record(entries));
	await controller.synchronize();
	expect(api.postInput).toHaveBeenCalledExactlyOnceWith(
		'one',
		{ type: 'continue' },
		expect.any(AbortSignal)
	);
});

test('dismissal_stays_available_while_the_session_compacts', async () => {
	vi.mocked(api.getSession).mockResolvedValue(compacting([questionBatch('one')]));
	await controller.load();
	await controller.dismissPending(controller.pendingQuestion!);
	expect(api.dismissQuestion).toHaveBeenCalledOnce();
});

test('a_pending_question_and_continuation_ignore_a_compaction_marker_at_the_end', async () => {
	const marker: api.Entry = {
		kind: 'marker',
		entry_id: 'c',
		marker_type: 'compaction',
		content: 'Summary',
		display: true
	};
	vi.mocked(api.getSession).mockResolvedValue(record([questionBatch('one'), marker]));
	await controller.load();
	expect(controller.pendingQuestion?.toolCallId).toBe('one');
	vi.mocked(api.getSession).mockResolvedValue(
		record([questionBatch('one'), questionResult('one'), marker])
	);
	await controller.synchronize();
	expect(api.postInput).toHaveBeenCalledExactlyOnceWith(
		'one',
		{ type: 'continue' },
		expect.any(AbortSignal)
	);
});

test('a_failure_behind_a_compaction_marker_shows_but_cannot_retry', async () => {
	const failed: api.Entry = {
		kind: 'assistant',
		entry_id: 'a',
		parts: [],
		stop_reason: 'error',
		error_text: 'Provider failed'
	};
	const marker: api.Entry = {
		kind: 'marker',
		entry_id: 'c',
		marker_type: 'compaction',
		content: 'Summary',
		display: true
	};
	vi.mocked(api.getSession).mockResolvedValue(record([failed, marker]));
	await controller.load();
	expect(controller.error).toBe('Provider failed');
	expect(controller.retryBlocked).toBe(true);
	vi.mocked(api.getSession).mockResolvedValue(record([marker, failed]));
	await controller.synchronize();
	expect(controller.retryBlocked).toBe(false);
});

test('text_steers_while_busy_and_sends_normally_when_idle', async () => {
	await controller.load();
	controller.busy = true;
	controller.draft = 'Use a bike';
	await controller.send();
	expect(api.steerSession).toHaveBeenCalledWith(
		'one',
		expect.stringMatching(/^steer_/),
		'Use a bike'
	);
	expect(api.postInput).not.toHaveBeenCalled();
	expect(controller.draft).toBe('');
	controller.busy = false;
	controller.draft = 'Next example';
	await controller.send();
	expect(api.postInput).toHaveBeenCalledWith(
		'one',
		{ type: 'text', text: 'Next example' },
		expect.any(AbortSignal)
	);
});

test('a_raced_steer_409_falls_back_to_a_normal_send', async () => {
	await controller.load();
	controller.busy = true;
	controller.draft = 'Use a bike';
	vi.mocked(api.steerSession).mockRejectedValueOnce(new api.ApiError(409, 'not_running', 'Ended'));
	await controller.send();
	expect(api.postInput).toHaveBeenCalledExactlyOnceWith(
		'one',
		{ type: 'text', text: 'Use a bike' },
		expect.any(AbortSignal)
	);
	expect(controller.queuedSteers).toEqual([]);
});

test('queued_steer_clears_when_context_update_lands_it', async () => {
	await controller.load();
	controller.busy = true;
	controller.draft = 'Use a bike';
	await controller.send();
	const [steer] = controller.queuedSteers;
	expect(steer?.text).toBe('Use a bike');
	const entry: api.Entry = { kind: 'user', entry_id: steer!.id, text: steer!.text };
	vi.mocked(api.streamTurn).mockImplementation(async (_, receive) => {
		receive({ type: 'context_update', entries: [entry] });
		expect(controller.queuedSteers).toEqual([]);
		expect(controller.entries).toEqual([entry]);
		receive({ type: 'context_update', entries: [entry] });
		expect(controller.entries).toEqual([entry]);
		vi.mocked(api.getSession).mockResolvedValue(record([entry]));
		return true;
	});
	await controller.attach();
});

test('invert_switch_writes_the_silent_view_and_survives_record_reload', async () => {
	await controller.load();
	controller.setInverted('steer_demo', true);
	expect(api.setArtifactView).toHaveBeenCalledWith('one', 'steer_demo', true);
	expect(controller.record?.artifact_views).toEqual({ steer_demo: true });
	vi.mocked(api.getSession).mockResolvedValue({
		...record(),
		artifact_views: { steer_demo: true }
	});
	await controller.synchronize();
	expect(controller.record?.artifact_views?.steer_demo).toBe(true);
});
