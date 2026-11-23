import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { SessionRows } from './session-rows.svelte';
import * as api from '#lib/api/client.js';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	listSessions: vi.fn(),
	getSessionItem: vi.fn()
}));

const row = (
	id: string,
	updated: string,
	patch: Partial<api.SessionItem> = {}
): api.SessionItem => ({
	id,
	title: id,
	kind: 'teach',
	updated_at: `2026-01-01T00:0${updated}:00Z`,
	busy: false,
	...patch
});
const ids = (rows: SessionRows) => rows.rows.map((item) => item.id);
const pending = <T>() => {
	let resolve!: (value: T) => void;
	let reject!: (error: unknown) => void;
	const promise = new Promise<T>((done, fail) => {
		resolve = done;
		reject = fail;
	});
	return { promise, resolve, reject };
};
let rows: SessionRows;
beforeEach(() => {
	vi.mocked(api.listSessions).mockReset();
	vi.mocked(api.getSessionItem).mockReset();
	rows = new SessionRows();
});
afterEach(() => rows.dispose());

test('a_changed_session_is_read_alone_and_moves_to_the_top', async () => {
	vi.mocked(api.listSessions).mockResolvedValue([row('a', '3'), row('b', '2'), row('c', '1')]);
	rows.reload();
	await expect.poll(() => ids(rows)).toEqual(['a', 'b', 'c']);
	vi.mocked(api.getSessionItem).mockResolvedValue(row('c', '9', { busy: true }));
	rows.changed('c');
	await expect.poll(() => ids(rows)).toEqual(['c', 'a', 'b']);
	expect(rows.rows[0].busy).toBe(true);
	expect(api.listSessions).toHaveBeenCalledTimes(1);
	expect(api.getSessionItem).toHaveBeenCalledExactlyOnceWith('c', expect.any(AbortSignal));
});

test('a_new_session_is_inserted_by_recency_and_a_gone_session_is_dropped', async () => {
	vi.mocked(api.listSessions).mockResolvedValue([row('a', '3'), row('c', '1')]);
	rows.reload();
	await expect.poll(() => ids(rows)).toEqual(['a', 'c']);
	vi.mocked(api.getSessionItem).mockResolvedValue(row('b', '2'));
	rows.changed('b');
	await expect.poll(() => ids(rows)).toEqual(['a', 'b', 'c']);
	vi.mocked(api.getSessionItem).mockResolvedValue(null);
	rows.changed('a');
	await expect.poll(() => ids(rows)).toEqual(['b', 'c']);
	expect(rows.error).toBeNull();
});

test('an_event_during_a_read_gets_a_later_read_so_a_stale_answer_never_stays', async () => {
	vi.mocked(api.listSessions).mockResolvedValue([row('a', '1')]);
	rows.reload();
	await expect.poll(() => ids(rows)).toEqual(['a']);
	const first = pending<api.SessionItem>();
	vi.mocked(api.getSessionItem)
		.mockReturnValueOnce(first.promise)
		.mockResolvedValueOnce(row('a', '5', { pending_question: true }));
	rows.changed('a');
	await expect.poll(() => vi.mocked(api.getSessionItem).mock.calls.length).toBe(1);
	rows.changed('a');
	rows.changed('a');
	expect(api.getSessionItem).toHaveBeenCalledTimes(1);
	first.resolve(row('a', '2', { busy: true }));
	await expect.poll(() => rows.rows[0].pending_question).toBe(true);
	expect(api.getSessionItem).toHaveBeenCalledTimes(2);
	expect(rows.rows[0].busy).toBe(false);
});

test('a_deleted_session_stays_gone_when_an_older_read_still_lists_it', async () => {
	const list = pending<api.SessionItem[]>();
	vi.mocked(api.listSessions).mockReturnValue(list.promise);
	rows.reload();
	rows.removed('a');
	list.resolve([row('a', '2'), row('b', '1')]);
	await expect.poll(() => ids(rows)).toEqual(['b']);
	vi.mocked(api.getSessionItem).mockResolvedValue(row('a', '3'));
	rows.changed('a');
	await expect.poll(() => api.getSessionItem).toHaveBeenCalledTimes(1);
	expect(ids(rows)).toEqual(['b']);
});

test('a_full_reload_follows_a_session_less_event_and_recovers_missed_changes', async () => {
	vi.mocked(api.listSessions).mockResolvedValueOnce([row('a', '1')]);
	rows.reload();
	await expect.poll(() => ids(rows)).toEqual(['a']);
	vi.mocked(api.listSessions).mockResolvedValueOnce([row('b', '2'), row('a', '1')]);
	rows.changed('');
	await expect.poll(() => ids(rows)).toEqual(['b', 'a']);
	expect(api.getSessionItem).not.toHaveBeenCalled();
});

test('a_full_read_covers_row_events_queued_before_it_starts', async () => {
	const first = pending<api.SessionItem>();
	vi.mocked(api.getSessionItem).mockReturnValueOnce(first.promise);
	vi.mocked(api.listSessions).mockResolvedValue([row('x', '2'), row('a', '1')]);
	rows.changed('x');
	rows.changed('a');
	rows.reload();
	first.resolve(row('x', '2'));
	await expect.poll(() => ids(rows)).toEqual(['x', 'a']);
	expect(api.getSessionItem).toHaveBeenCalledExactlyOnceWith('x', expect.any(AbortSignal));
	expect(api.listSessions).toHaveBeenCalledTimes(1);
});

test('a_failed_read_shows_its_error_and_the_next_success_clears_it', async () => {
	vi.mocked(api.getSessionItem).mockRejectedValueOnce(new Error('offline'));
	rows.changed('a');
	await expect.poll(() => rows.error).toBe('offline');
	vi.mocked(api.getSessionItem).mockResolvedValue(row('a', '1'));
	rows.changed('a');
	await expect.poll(() => rows.error).toBeNull();
	expect(ids(rows)).toEqual(['a']);
});
