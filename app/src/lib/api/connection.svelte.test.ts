import { beforeEach, expect, test, vi } from 'vitest';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { SidecarState } from './connection.svelte';
import { markStartup } from './startup';

vi.mock('@tauri-apps/api/core', () => ({
	invoke: vi.fn(),
	isTauri: vi.fn()
}));

beforeEach(() => {
	vi.mocked(invoke).mockReset();
	vi.mocked(isTauri).mockReturnValue(true);
});

test('the_shell_is_pending_until_the_sidecar_connection_arrives_then_ready', async () => {
	let release!: (value: { port: number; token: string }) => void;
	vi.mocked(invoke).mockImplementation(() => new Promise((resolve) => (release = resolve)));
	const sidecar = new SidecarState();
	const pending = sidecar.connect();
	expect(sidecar.status).toBe('pending');
	release({ port: 4321, token: 'secret' });
	expect(await pending).toEqual({ base: 'http://127.0.0.1:4321', token: 'secret' });
	expect(sidecar.status).toBe('ready');
	expect(await sidecar.connect()).toEqual({ base: 'http://127.0.0.1:4321', token: 'secret' });
	expect(invoke).toHaveBeenCalledExactlyOnceWith('sidecar_connection');
});

test('a_failed_start_remains_stable_when_other_requests_connect', async () => {
	let recover!: (value: { port: number; token: string }) => void;
	vi.mocked(invoke)
		.mockImplementationOnce(() =>
			Promise.reject('The sidecar did not start. See /tmp/verstehen.log')
		)
		.mockImplementationOnce(() => new Promise((resolve) => (recover = resolve)));
	const sidecar = new SidecarState();
	await expect(sidecar.connect()).rejects.toThrow('did not start');
	expect(sidecar.status).toBe('failed');
	expect(sidecar.failure).toBe('The sidecar did not start. See /tmp/verstehen.log');
	const retry = sidecar.connect();
	expect(sidecar.status).toBe('failed');
	recover({ port: 4321, token: 'secret' });
	await retry;
	expect(sidecar.status).toBe('ready');
	expect(sidecar.failure).toBeNull();
});

test('a_browser_is_ready_without_asking_the_shell', async () => {
	vi.mocked(isTauri).mockReturnValue(false);
	const sidecar = new SidecarState();
	expect(await sidecar.connect()).toEqual({ base: '' });
	expect(sidecar.status).toBe('ready');
	expect(invoke).not.toHaveBeenCalled();
});

test('each_startup_milestone_is_marked_once_and_reported_to_the_shell', async () => {
	vi.mocked(invoke).mockResolvedValue(undefined);
	const mark = vi.spyOn(performance, 'mark');
	markStartup('composer_usable');
	markStartup('composer_usable');
	markStartup('models_displayed');
	expect(mark.mock.calls.map(([name]) => name)).toEqual([
		'verstehen:composer_usable',
		'verstehen:models_displayed'
	]);
	expect(vi.mocked(invoke).mock.calls).toEqual([
		['startup_mark', { name: 'composer_usable' }],
		['startup_mark', { name: 'models_displayed' }]
	]);
});
