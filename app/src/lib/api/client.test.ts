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
