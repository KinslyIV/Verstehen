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
	expect(Object.fromEntries(preferenceFiles)).toEqual(paired);
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
	await dropToken();
	expect(await loadConnection()).toEqual({ server_url: paired.server_url });
	expect(Object.fromEntries(preferenceFiles)).toEqual({ server_url: paired.server_url });
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
	'example.com'
])('the server address "%s" is refused', async (input) => {
	const { parseServerAddress } = await import('./connection');
	expect(() => parseServerAddress(input)).toThrow();
});

test('debug builds accept their extra hosts only', async () => {
	const { parseServerAddress } = await import('./connection');
	expect(parseServerAddress('10.0.2.2:8420', ['10.0.2.2'])).toBe('http://10.0.2.2:8420');
	expect(() => parseServerAddress('10.0.2.3:8420', ['10.0.2.2'])).toThrow();
});
