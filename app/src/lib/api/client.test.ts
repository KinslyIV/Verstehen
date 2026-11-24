import { afterEach, expect, test, vi } from 'vitest';
import { invoke, isTauri } from '@tauri-apps/api/core';
import {
	deleteSession,
	health,
	listSessions,
	refreshModels,
	revokeOwnDevice,
	setToken,
	streamTurn
} from './client';

vi.mock('@tauri-apps/api/core', () => ({
	invoke: vi.fn(),
	isTauri: vi.fn().mockReturnValue(false)
}));

afterEach(() => {
	setToken(undefined);
	vi.unstubAllGlobals();
	vi.mocked(isTauri).mockReturnValue(false);
});

test.each([undefined, 'test-token'])('health sends only a configured token (%s)', async (token) => {
	const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok' })));
	vi.stubGlobal('fetch', request);
	setToken(token);
	expect(await health()).toEqual({ status: 'ok' });
	expect(request).toHaveBeenCalledWith('/api/health', {
		headers: token ? { 'x-verstehen-token': token } : {}
	});
});

test('health reports an HTTP failure', async () => {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 503 })));
	await expect(health()).rejects.toThrow('HTTP 503');
});

test('desktop JSON and SSE requests share one connection and use its URL and token', async () => {
	vi.mocked(isTauri).mockReturnValue(true);
	vi.mocked(invoke).mockResolvedValue({ port: 12345, token: 'desktop-token' });
	const request = vi.fn().mockImplementation((url: string) => {
		if (url.endsWith('/stream')) return Promise.resolve(new Response('data: [DONE]\n\n'));
		const body = url.endsWith('/sessions') ? { sessions: [] } : { status: 'ok' };
		return Promise.resolve(new Response(JSON.stringify(body)));
	});
	vi.stubGlobal('fetch', request);
	const signal = new AbortController().signal;
	await Promise.all([health(), health()]);
	expect(await listSessions()).toEqual([]);
	expect(await streamTurn('session-id', vi.fn(), signal)).toBe(true);
	expect(invoke).toHaveBeenCalledExactlyOnceWith('sidecar_connection');
	expect(request).toHaveBeenCalledTimes(4);
	expect(request).toHaveBeenCalledWith('http://127.0.0.1:12345/api/health', {
		headers: { 'x-verstehen-token': 'desktop-token' }
	});
	expect(request).toHaveBeenCalledWith('http://127.0.0.1:12345/api/sessions/session-id/stream', {
		signal,
		headers: { 'x-verstehen-token': 'desktop-token' }
	});
});

test('desktop requests can retry after a shared connection lookup fails', async () => {
	vi.resetModules();
	const { health } = await import('./client');
	vi.mocked(isTauri).mockReturnValue(true);
	vi.mocked(invoke)
		.mockClear()
		.mockRejectedValueOnce('Sidecar is not ready')
		.mockResolvedValueOnce({ port: 12345, token: 'desktop-token' });
	const request = vi.fn().mockResolvedValue(new Response('{"status":"ok"}'));
	vi.stubGlobal('fetch', request);

	await Promise.all([
		expect(health()).rejects.toThrow('Sidecar is not ready'),
		expect(health()).rejects.toThrow('Sidecar is not ready')
	]);
	expect(invoke).toHaveBeenCalledTimes(1);
	expect(request).not.toHaveBeenCalled();
	expect(await health()).toEqual({ status: 'ok' });
	expect(invoke).toHaveBeenCalledTimes(2);
});

test('SSE decodes split UTF-8, CRLF frames, comments, and terminal marker', async () => {
	const { readEvents } = await import('./client');
	const bytes = new TextEncoder().encode(
		': ping\r\n\r\nevent: chats-changed\r\ndata: {"text":"中文"}\r\n\r\ndata: [DONE]\n\n'
	);
	const events: string[][] = [];
	const response = new Response(
		new ReadableStream({
			start(controller) {
				for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
				controller.close();
			}
		})
	);
	expect(await readEvents(response, (event, data) => events.push([event, data]))).toBe(true);
	expect(events).toEqual([['chats-changed', '{"text":"中文"}']]);
});
test('SSE reports an early end without DONE', async () => {
	const { readEvents } = await import('./client');
	expect(await readEvents(new Response('data: {}\n\n'), () => {})).toBe(false);
});

test('model_refusals_retain_the_reason_and_missing_slots', async () => {
	const { getModels, ApiError } = await import('./client');
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue(
			new Response(
				JSON.stringify({
					code: 'model_unavailable',
					error: 'Unavailable',
					reason: 'Sign in again.',
					missing: ['cheap']
				}),
				{ status: 503 }
			)
		)
	);
	await expect(getModels()).rejects.toMatchObject({
		code: 'model_unavailable',
		reason: 'Sign in again.',
		missing: ['cheap']
	});
	await expect(getModels()).rejects.toBeInstanceOf(ApiError);
});

test('desktop_sign_in_opens_the_system_browser_through_the_existing_shell', async () => {
	const { openExternal } = await import('./client');
	vi.mocked(isTauri).mockReturnValue(true);
	vi.mocked(invoke).mockClear().mockResolvedValue(undefined);
	await openExternal('https://auth.openai.com/authorize');
	expect(invoke).toHaveBeenCalledExactlyOnceWith('plugin:shell|open', {
		path: 'https://auth.openai.com/authorize'
	});
});

test('browser_sign_in_opens_a_new_tab_without_an_opener', async () => {
	const { openExternal } = await import('./client');
	vi.mocked(invoke).mockClear();
	const open = vi.fn();
	vi.stubGlobal('window', { open });
	await openExternal('https://auth.openai.com/authorize');
	expect(open).toHaveBeenCalledExactlyOnceWith(
		'https://auth.openai.com/authorize',
		'_blank',
		'noopener,noreferrer'
	);
	expect(invoke).not.toHaveBeenCalled();
});

test('void_requests_drain_their_response_body_before_resolving', async () => {
	let controller!: ReadableStreamDefaultController<Uint8Array>;
	const streamResponse = new Response(
		new ReadableStream({
			start(ctrl) {
				controller = ctrl;
			}
		})
	);
	const sessionResponse = new Response('{"ok":true}');
	const fetchMock = vi
		.fn()
		.mockResolvedValueOnce(streamResponse)
		.mockResolvedValueOnce(new Response(null, { status: 204 }))
		.mockResolvedValueOnce(sessionResponse);
	vi.stubGlobal('fetch', fetchMock);

	let settled = false;
	const pending = revokeOwnDevice('device-1').then(() => {
		settled = true;
	});
	await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
	await Promise.resolve();
	await Promise.resolve();
	expect(settled).toBe(false);

	controller.enqueue(new TextEncoder().encode('{"ok":true}'));
	controller.close();
	await pending;
	expect(settled).toBe(true);
	expect(streamResponse.bodyUsed).toBe(true);

	await expect(refreshModels()).resolves.toBeUndefined();
	await expect(deleteSession('s1', 'preserve-graph')).resolves.toBeUndefined();
	expect(sessionResponse.bodyUsed).toBe(true);
});
