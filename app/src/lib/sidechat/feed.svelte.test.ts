import { afterEach, beforeEach, expect, test, vi, type MockInstance } from 'vitest';
import * as api from '#lib/api/client.js';
import { live } from '#lib/api/live.svelte.js';
import { SideChatFeed } from './feed.svelte.js';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getSideChats: vi.fn(),
	askSideChat: vi.fn(),
	streamSideChat: vi.fn(),
	stopSideChat: vi.fn()
}));

const thread: api.SideThread = {
	id: 'side_b',
	anchor: { entry_id: 'b', block_text: '' },
	messages: []
};
let feed: SideChatFeed;
let wait: MockInstance<typeof live.wait>;

beforeEach(() => {
	vi.mocked(api.getSideChats)
		.mockReset()
		.mockResolvedValue({ threads: [thread], answering: {} });
	vi.mocked(api.streamSideChat).mockReset();
	wait = vi.spyOn(live, 'wait').mockResolvedValue();
	feed = new SideChatFeed(
		'one',
		() => 'b',
		() => ''
	);
	feed.threads = [thread];
	feed.live = { side_b: '' };
});
afterEach(() => {
	feed.dispose();
	wait.mockRestore();
});

test('a_dropped_connection_waits_and_reattaches_to_the_running_side_answer', async () => {
	vi.mocked(api.streamSideChat)
		.mockImplementationOnce(async (_id, _thread, receive) => {
			receive({ type: 'text', text: 'Partial' });
			throw new TypeError('Failed to fetch');
		})
		.mockRejectedValueOnce(new TypeError('Failed to fetch'))
		.mockImplementationOnce(async (_id, _thread, receive) => {
			receive({ type: 'text', text: 'Partial and the rest' });
			receive({ type: 'done', thread });
			return true;
		});
	feed.open('b');
	await vi.waitFor(() => expect(feed.answering).toBe(false));
	expect(api.streamSideChat).toHaveBeenCalledTimes(3);
	expect(wait.mock.calls.map(([attempt]) => attempt)).toEqual([0, 1]);
	expect(feed.error).toBeUndefined();
});

test('a_server_error_still_fails_the_answer_instead_of_waiting', async () => {
	vi.mocked(api.streamSideChat).mockRejectedValue(new api.ApiError(500, undefined, 'boom'));
	feed.open('b');
	await vi.waitFor(() => expect(feed.error).toBe('boom'));
	expect(wait).not.toHaveBeenCalled();
	expect(feed.answering).toBe(false);
});

test('disposing_stops_waiting_and_reattaching', async () => {
	vi.mocked(api.streamSideChat).mockRejectedValue(new TypeError('Failed to fetch'));
	wait.mockImplementation(async () => {
		feed.dispose();
	});
	feed.open('b');
	await vi.waitFor(() => expect(wait).toHaveBeenCalledTimes(1));
	await new Promise((resolve) => setTimeout(resolve, 20));
	expect(api.streamSideChat).toHaveBeenCalledTimes(1);
	expect(feed.error).toBeUndefined();
});
