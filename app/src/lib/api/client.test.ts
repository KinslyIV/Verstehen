import { afterEach, expect, test, vi } from 'vitest';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { health, setToken } from './client';

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

test('desktop requests share one connection and use its URL and token', async () => {
	vi.mocked(isTauri).mockReturnValue(true);
	vi.mocked(invoke).mockResolvedValue({ port: 12345, token: 'desktop-token' });
	const request = vi
		.fn()
		.mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ status: 'ok' }))));
	vi.stubGlobal('fetch', request);
	await Promise.all([health(), health()]);
	expect(invoke).toHaveBeenCalledExactlyOnceWith('sidecar_connection');
	expect(request).toHaveBeenCalledTimes(2);
	expect(request).toHaveBeenCalledWith('http://127.0.0.1:12345/api/health', {
		headers: { 'x-verstehen-token': 'desktop-token' }
	});
});
