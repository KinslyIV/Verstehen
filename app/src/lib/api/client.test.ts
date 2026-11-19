import { afterEach, expect, test, vi } from 'vitest';
import { health, setToken } from './client';

afterEach(() => {
	setToken(undefined);
	vi.unstubAllGlobals();
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
