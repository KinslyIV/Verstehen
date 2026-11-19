import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { SessionController } from './controller.svelte';
import * as api from '#lib/api/client.js';
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getSession: vi.fn(),
	postInput: vi.fn(),
	streamTurn: vi.fn()
}));
const record = (entries: api.Entry[] = [], busy = false): api.SessionDetail => ({
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
	vi.mocked(api.postInput).mockReset().mockResolvedValue();
	vi.mocked(api.streamTurn).mockReset().mockResolvedValue(true);
	controller = new SessionController('one', 1, 20);
});
afterEach(() => controller.dispose());
test('refused_send_restores_draft_and_shows_no_model_notice', async () => {
	await controller.load();
	controller.draft = 'Algebra';
	vi.mocked(api.postInput).mockRejectedValue(
		new api.ApiError(503, 'models_not_configured', 'missing')
	);
	await controller.send();
	expect(controller.draft).toBe('Algebra');
	expect(controller.notice).toBe('No model is set up yet.');
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
