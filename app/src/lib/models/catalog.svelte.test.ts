import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import * as api from '#lib/api/client.js';
import { ModelCatalogState, REFRESH_POLL_MS } from './catalog.svelte.js';
import { testCatalog } from './test-fixtures.js';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getModels: vi.fn(),
	refreshModels: vi.fn()
}));
vi.mock('#lib/api/startup.js', () => ({ markStartup: vi.fn() }));

const saved = (label: string): api.ModelCatalog => {
	const catalog = structuredClone(testCatalog);
	catalog.accounts[0].account.label = label;
	return catalog;
};
const label = (state: ModelCatalogState) => state.catalog?.accounts[0].account.label;

beforeEach(() => {
	vi.clearAllMocks();
	vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

test('the_saved_catalog_shows_before_any_account_is_contacted', async () => {
	vi.mocked(api.getModels).mockResolvedValue(saved('saved'));
	const state = new ModelCatalogState();
	await state.load();
	expect(label(state)).toBe('saved');
	expect(api.refreshModels).not.toHaveBeenCalled();
	expect(state.settled).toBe(true);
});

test('an_empty_catalog_is_not_settled_until_a_refresh_finishes', async () => {
	vi.mocked(api.getModels).mockResolvedValue({ accounts: [], slots: {} });
	const state = new ModelCatalogState();
	await state.load();
	expect(state.settled).toBe(false);
	await state.refresh();
	expect(state.settled).toBe(true);
});

test('an_older_read_that_finishes_last_is_ignored', async () => {
	let finishFirst!: (catalog: api.ModelCatalog) => void;
	vi.mocked(api.getModels)
		.mockImplementationOnce(() => new Promise((resolve) => (finishFirst = resolve)))
		.mockResolvedValueOnce(saved('newer'));
	const state = new ModelCatalogState();
	const first = state.load();
	await state.load();
	finishFirst(saved('older'));
	await first;
	expect(label(state)).toBe('newer');
});

test('a_read_from_the_previous_server_cannot_repopulate_a_reset_catalog', async () => {
	let finish!: (catalog: api.ModelCatalog) => void;
	vi.mocked(api.getModels).mockImplementationOnce(
		() => new Promise((resolve) => (finish = resolve))
	);
	const state = new ModelCatalogState();
	const reading = state.start();
	state.reset();
	finish(saved('old server'));
	await reading;
	expect(state.catalog).toBeUndefined();
	expect(api.refreshModels).not.toHaveBeenCalled();
});

test('each_account_appears_as_it_finishes_while_the_refresh_is_still_running', async () => {
	let finish!: () => void;
	vi.mocked(api.refreshModels).mockImplementation(
		() => new Promise((resolve) => (finish = () => resolve()))
	);
	vi.mocked(api.getModels).mockResolvedValue(saved('first'));
	const state = new ModelCatalogState();
	const refreshing = state.refresh();
	expect(state.refreshing).toBe(true);
	await vi.advanceTimersByTimeAsync(REFRESH_POLL_MS);
	expect(label(state)).toBe('first');
	expect(state.refreshing).toBe(true);
	vi.mocked(api.getModels).mockResolvedValue(saved('final'));
	finish();
	await refreshing;
	expect(label(state)).toBe('final');
	expect(state.refreshing).toBe(false);
	const reads = vi.mocked(api.getModels).mock.calls.length;
	await vi.advanceTimersByTimeAsync(REFRESH_POLL_MS * 3);
	expect(api.getModels).toHaveBeenCalledTimes(reads);
});

test('a_plain_refresh_joins_the_one_in_flight_and_a_forced_one_starts_another', async () => {
	vi.mocked(api.getModels).mockResolvedValue(saved('saved'));
	vi.mocked(api.refreshModels).mockImplementation(() => new Promise(() => {}));
	const state = new ModelCatalogState();
	const first = state.refresh();
	expect(state.refresh()).toBe(first);
	void state.refresh(true);
	expect(vi.mocked(api.refreshModels).mock.calls).toEqual([[false], [true]]);
});

test('a_failed_read_keeps_the_saved_catalog_and_reports_the_error', async () => {
	vi.mocked(api.getModels).mockResolvedValueOnce(saved('saved'));
	const state = new ModelCatalogState();
	await state.load();
	vi.mocked(api.getModels).mockRejectedValueOnce(new Error('offline'));
	await state.load();
	expect(label(state)).toBe('saved');
	expect(state.error).toBe('offline');
});

test('a_failed_refresh_resolves_to_its_message_and_still_rereads_the_saved_catalog', async () => {
	vi.mocked(api.getModels).mockResolvedValue(saved('saved'));
	vi.mocked(api.refreshModels).mockRejectedValue(new Error('HTTP 500'));
	const state = new ModelCatalogState();
	expect(await state.refresh(true)).toBe('HTTP 500');
	expect(label(state)).toBe('saved');
});
