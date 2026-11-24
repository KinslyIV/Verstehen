import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { LiveConnection, isNetworkFailure } from './live.svelte.js';

let live: LiveConnection;

function setVisibility(state: 'visible' | 'hidden') {
	Object.defineProperty(document, 'visibilityState', { configurable: true, value: state });
	document.dispatchEvent(new Event('visibilitychange'));
}

beforeEach(() => {
	vi.useFakeTimers();
	live = new LiveConnection();
});

afterEach(() => {
	live.dispose();
	setVisibility('visible');
	vi.useRealTimers();
});

test('a_failed_fetch_is_a_network_failure_and_an_api_error_is_not', () => {
	expect(isNetworkFailure(new TypeError('Failed to fetch'))).toBe(true);
	expect(isNetworkFailure(new Error('HTTP 500'))).toBe(false);
});

test('waits_back_off_one_two_five_then_ten_seconds', async () => {
	const signal = new AbortController().signal;
	for (const [attempt, delay] of [
		[0, 1000],
		[1, 2000],
		[2, 5000],
		[3, 10_000],
		[9, 10_000]
	] as const) {
		let done = false;
		void live.wait(attempt, signal).then(() => (done = true));
		await vi.advanceTimersByTimeAsync(delay - 1);
		expect(done).toBe(false);
		await vi.advanceTimersByTimeAsync(1);
		expect(done).toBe(true);
	}
});

test('a_wait_never_ends_while_hidden_and_ends_on_return', async () => {
	let done = false;
	setVisibility('hidden');
	void live.wait(0, new AbortController().signal).then(() => (done = true));
	await vi.advanceTimersByTimeAsync(60_000);
	expect(done).toBe(false);
	setVisibility('visible');
	await vi.advanceTimersByTimeAsync(0);
	expect(done).toBe(true);
});

test('the_online_event_wakes_a_waiting_stream', async () => {
	let done = false;
	void live.wait(3, new AbortController().signal).then(() => (done = true));
	window.dispatchEvent(new Event('online'));
	await vi.advanceTimersByTimeAsync(0);
	expect(done).toBe(true);
});

test('follow_reopens_a_failed_stream_and_refetches_once_it_is_back', async () => {
	const lifetime = new AbortController();
	const reconnected = vi.fn();
	let opens = 0;
	const following = live.follow(
		async (signal, opened) => {
			opens++;
			if (opens === 1) throw new TypeError('Failed to fetch');
			opened();
			await new Promise<void>((resolve) => signal.addEventListener('abort', () => resolve()));
		},
		reconnected,
		lifetime.signal
	);
	await vi.advanceTimersByTimeAsync(0);
	expect(live.reconnecting).toBe(true);
	await vi.advanceTimersByTimeAsync(1000);
	expect(opens).toBe(2);
	expect(reconnected).toHaveBeenCalledOnce();
	expect(live.reconnecting).toBe(false);
	lifetime.abort();
	await following;
});

test('the_first_open_does_not_count_as_a_reconnection', async () => {
	const lifetime = new AbortController();
	const reconnected = vi.fn();
	const following = live.follow(
		async (signal, opened) => {
			opened();
			await new Promise<void>((resolve) => signal.addEventListener('abort', () => resolve()));
		},
		reconnected,
		lifetime.signal
	);
	await vi.advanceTimersByTimeAsync(0);
	expect(reconnected).not.toHaveBeenCalled();
	lifetime.abort();
	await following;
});

test('reconnecting_is_not_shown_while_the_app_is_hidden', async () => {
	const lifetime = new AbortController();
	const following = live.follow(
		async () => {
			throw new TypeError('Failed to fetch');
		},
		() => {},
		lifetime.signal
	);
	await vi.advanceTimersByTimeAsync(0);
	expect(live.reconnecting).toBe(true);
	setVisibility('hidden');
	expect(live.reconnecting).toBe(false);
	lifetime.abort();
	await following;
});
