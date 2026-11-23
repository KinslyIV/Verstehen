import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { Capacitor } from '@capacitor/core';
import { Preferences } from '@capacitor/preferences';

vi.mock('@capacitor/core', () => ({ Capacitor: { isNativePlatform: vi.fn() } }));
vi.mock('@capacitor/preferences', () => ({
	Preferences: { get: vi.fn(), set: vi.fn(), remove: vi.fn(), clear: vi.fn() }
}));

const paired = { server_url: 'http://100.64.0.7:8420', device_id: 'device-1', token: 'secret' };
let browserFiles = new Map<string, string>();
let preferenceFiles = new Map<string, string>();

beforeEach(() => {
	vi.resetModules();
	browserFiles = new Map();
	preferenceFiles = new Map();
	vi.stubGlobal('localStorage', {
		getItem: (key: string) => browserFiles.get(key) ?? null,
		setItem: (key: string, value: string) => browserFiles.set(key, value),
		removeItem: (key: string) => browserFiles.delete(key)
	});
	vi.mocked(Preferences.get).mockImplementation(async ({ key }) => ({
		value: preferenceFiles.get(key) ?? null
	}));
	vi.mocked(Preferences.set).mockImplementation(async ({ key, value }) => {
		preferenceFiles.set(key, value);
	});
	vi.mocked(Preferences.remove).mockImplementation(async ({ key }) => {
		preferenceFiles.delete(key);
	});
	vi.mocked(Preferences.clear).mockImplementation(async () => preferenceFiles.clear());
});

afterEach(() => vi.unstubAllGlobals());

test('a browser build stays in sidecar mode and the Android app is always remote', async () => {
	const { clientMode } = await import('./connection');
	vi.mocked(Capacitor.isNativePlatform).mockReturnValue(false);
	expect(clientMode()).toBe('sidecar');
	vi.mocked(Capacitor.isNativePlatform).mockReturnValue(true);
	expect(clientMode()).toBe('remote');
});

test('the Android app keeps its connection in Capacitor Preferences', async () => {
	vi.mocked(Capacitor.isNativePlatform).mockReturnValue(true);
	const { loadConnection, saveConnection } = await import('./connection');
	await saveConnection(paired);
	expect([...preferenceFiles.keys()]).toEqual(['verstehen-connection']);
	expect(JSON.parse(preferenceFiles.get('verstehen-connection')!)).toEqual(paired);
	expect(Preferences.set).toHaveBeenCalledTimes(1);
	vi.resetModules();
	expect(await (await import('./connection')).loadConnection()).toEqual(paired);
	expect(await loadConnection()).toEqual(paired);
	expect(browserFiles.size).toBe(0);
});

test('headless flows keep the connection in browser storage', async () => {
	vi.mocked(Capacitor.isNativePlatform).mockReturnValue(false);
	const { loadConnection, saveConnection } = await import('./connection');
	await saveConnection(paired);
	vi.resetModules();
	expect(await (await import('./connection')).loadConnection()).toEqual(paired);
	expect(preferenceFiles.size).toBe(0);
	expect(loadConnection).toBeTypeOf('function');
});

test('dropping the token keeps the server address', async () => {
	vi.mocked(Capacitor.isNativePlatform).mockReturnValue(true);
	const { dropToken, isPaired, loadConnection, saveConnection } = await import('./connection');
	await saveConnection(paired);
	expect(await dropToken(paired.token)).toBe(true);
	expect(await loadConnection()).toEqual({ server_url: paired.server_url });
	expect(JSON.parse(preferenceFiles.get('verstehen-connection')!)).toEqual({
		server_url: paired.server_url
	});
	expect(isPaired(await loadConnection())).toBe(false);
});

test.each([
	['100.64.0.7:8420', 'http://100.64.0.7:8420'],
	[' http://100.127.255.255:9 ', 'http://100.127.255.255:9'],
	['100.100.1.1', 'http://100.100.1.1']
])('the server address %s is accepted', async (input, url) => {
	const { parseServerAddress } = await import('./connection');
	expect(parseServerAddress(input)).toBe(url);
});

test.each([
	'',
	'not a url',
	'100.64.0.7/api',
	'192.168.1.5:8420',
	'100.128.0.1',
	'100.63.0.1',
	'example.com',
	'100.64.0.0e0',
	'100.64.0.1e0',
	'100.64.0.0x1',
	'0x64400001',
	'1685323777',
	'100.064.0.1',
	'100.64.1',
	'100.64.0.1.',
	'100.64.0.+1',
	'user@100.64.0.1',
	'100.64.0.7:mistyped@100.64.0.7'
])('the server address "%s" is refused', async (input) => {
	const { parseServerAddress } = await import('./connection');
	expect(() => parseServerAddress(input)).toThrow();
});

test('debug builds accept their extra hosts only', async () => {
	const { parseServerAddress } = await import('./connection');
	expect(parseServerAddress('10.0.2.2:8420', ['10.0.2.2'])).toBe('http://10.0.2.2:8420');
	expect(() => parseServerAddress('10.0.2.3:8420', ['10.0.2.2'])).toThrow();
});

test('a rejection of an old token does not erase a newer pairing', async () => {
	vi.mocked(Capacitor.isNativePlatform).mockReturnValue(true);
	const { dropToken, loadConnection, saveConnection } = await import('./connection');
	await saveConnection(paired);
	const newer = { ...paired, device_id: 'device-2', token: 'fresh' };
	const saving = saveConnection(newer);
	expect(await dropToken(paired.token)).toBe(false);
	await saving;
	expect(await loadConnection()).toEqual(newer);
	expect(JSON.parse(preferenceFiles.get('verstehen-connection')!)).toEqual(newer);
});

test.each([
	[
		'per-field keys from an older build',
		{ server_url: paired.server_url, device_id: 'd', token: 't' }
	],
	[
		'a token without a device id',
		{ 'verstehen-connection': JSON.stringify({ server_url: paired.server_url, token: 't' }) }
	],
	[
		'a device id without a token',
		{ 'verstehen-connection': JSON.stringify({ server_url: paired.server_url, device_id: 'd' }) }
	],
	[
		'a record without a server address',
		{ 'verstehen-connection': JSON.stringify({ device_id: 'd', token: 't' }) }
	],
	['an unreadable record', { 'verstehen-connection': '{"server_url"' }]
])('%s loads as no connection and is deleted', async (_name, files) => {
	vi.mocked(Capacitor.isNativePlatform).mockReturnValue(true);
	for (const [key, value] of Object.entries(files)) preferenceFiles.set(key, value);
	const { loadConnection } = await import('./connection');
	expect(await loadConnection()).toEqual({});
	expect(preferenceFiles.size).toBe(0);
});
