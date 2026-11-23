import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { goto } from '$app/navigation';
import { listSessions, pairDevice } from './client';
import { clearConnection, loadConnection, saveConnection } from './connection';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('@capacitor/core', () => ({ Capacitor: { isNativePlatform: () => true } }));
vi.mock('@capacitor/preferences', () => {
	const files = new Map<string, string>();
	return {
		Preferences: {
			get: async ({ key }: { key: string }) => ({ value: files.get(key) ?? null }),
			set: async ({ key, value }: { key: string; value: string }) => files.set(key, value),
			remove: async ({ key }: { key: string }) => files.delete(key),
			clear: async () => files.clear()
		}
	};
});

const paired = { server_url: 'http://100.64.0.7:8420', device_id: 'device-1', token: 'secret' };

beforeEach(() => clearConnection());
afterEach(() => {
	vi.unstubAllGlobals();
	vi.mocked(goto).mockClear();
});

test('remote requests go to the paired server with a bearer token', async () => {
	await saveConnection(paired);
	const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({ sessions: [] })));
	vi.stubGlobal('fetch', request);
	expect(await listSessions()).toEqual([]);
	expect(request).toHaveBeenCalledWith('http://100.64.0.7:8420/api/sessions', {
		headers: { authorization: 'Bearer secret' }
	});
});

test('a 401 drops the token, keeps the address, and returns to pairing', async () => {
	await saveConnection(paired);
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })));
	await expect(listSessions()).rejects.toMatchObject({ status: 401 });
	expect(await loadConnection()).toEqual({ server_url: paired.server_url });
	expect(goto).toHaveBeenCalledWith('/pair');
});

test('a missing connection returns to pairing without calling the server', async () => {
	const request = vi.fn();
	vi.stubGlobal('fetch', request);
	await expect(listSessions()).rejects.toMatchObject({ status: 401 });
	expect(request).not.toHaveBeenCalled();
	expect(goto).toHaveBeenCalledWith('/pair');
});

test('pairing redeems the code and saves the connection', async () => {
	const request = vi
		.fn()
		.mockResolvedValue(new Response(JSON.stringify({ device_id: 'device-1', token: 'secret' })));
	vi.stubGlobal('fetch', request);
	expect(await pairDevice('100.64.0.7:8420', 'abcd2345', ' Phone ')).toEqual(paired);
	expect(request).toHaveBeenCalledWith('http://100.64.0.7:8420/api/auth/pair', {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ code: 'ABCD2345', device_name: 'Phone' })
	});
	expect(await loadConnection()).toEqual(paired);
});

test.each([
	[400, /invalid or has expired/],
	[429, /Too many wrong codes/],
	[500, /HTTP 500/]
])('pairing explains a %s response', async (status, message) => {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status })));
	await expect(pairDevice('100.64.0.7:8420', 'ABCD2345', 'Phone')).rejects.toThrow(message);
	expect(await loadConnection()).toEqual({});
});

test('pairing explains an unreachable server and a refused address', async () => {
	vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
	await expect(pairDevice('100.64.0.7:8420', 'ABCD2345', 'Phone')).rejects.toThrow(/Can't reach/);
	await expect(pairDevice('192.168.1.5:8420', 'ABCD2345', 'Phone')).rejects.toThrow(/Tailscale/);
});
