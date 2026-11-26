import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { userEvent } from 'vitest/browser';
import { listPlugins, setPluginEnabled, type PluginInfo } from '#lib/api/client.js';
import SettingsPlugins from '#lib/components/settings-plugins.svelte';
import PluginSettingsPage from './plugin-settings-page.svelte';
import { plugins } from './plugins.svelte.js';
import { PluginRuntime } from './runtime.svelte.js';

const { searchParams } = vi.hoisted(() => ({
	searchParams: new URLSearchParams()
}));

vi.mock('$app/state', () => ({
	page: {
		get url() {
			return { searchParams };
		}
	}
}));
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof import('#lib/api/client.js')>()),
	listPlugins: vi.fn(),
	setPluginEnabled: vi.fn(),
	refreshPlugins: vi.fn()
}));

let currentPlugin: PluginInfo;

beforeEach(() => {
	vi.clearAllMocks();
	searchParams.delete('plugin');
	currentPlugin = {
		id: 'slow',
		name: 'Slow Plugin',
		version: '1.0.0',
		enabled: false,
		status: 'disabled'
	};
	vi.mocked(listPlugins).mockImplementation(async () => ({
		plugins: [currentPlugin],
		directory: '/plugins'
	}));
	vi.mocked(setPluginEnabled).mockImplementation(async (_id, enabled) => {
		currentPlugin = {
			...currentPlugin,
			enabled,
			status: enabled ? 'activating' : 'disabled'
		};
		return currentPlugin;
	});
});

afterEach(() => {
	plugins.runtimes.clear();
	plugins.list = undefined;
	plugins.error = null;
});

test('the_switch_stays_usable_while_activating_and_live_notifications_settle_the_status', async () => {
	const screen = await render(SettingsPlugins);
	const toggle = screen.getByRole('switch', { name: 'Enable Slow Plugin' });
	await expect.element(toggle).not.toBeChecked();
	await expect.element(screen.getByTestId('plugin-status-slow')).toHaveTextContent('disabled');

	await toggle.click();
	expect(setPluginEnabled).toHaveBeenCalledWith('slow', true);
	await expect.element(screen.getByTestId('plugin-status-slow')).toHaveTextContent('activating');
	await expect.element(toggle).toBeChecked();
	await expect.element(toggle).toBeEnabled();

	currentPlugin = { ...currentPlugin, enabled: true, status: 'active' };
	plugins.deliver({ type: 'plugins-changed', session_id: '' });
	await expect.element(screen.getByTestId('plugin-status-slow')).toHaveTextContent('active');

	currentPlugin = { ...currentPlugin, enabled: true, status: 'activating' };
	plugins.deliver({ type: 'plugins-changed', session_id: '' });
	await expect.element(screen.getByTestId('plugin-status-slow')).toHaveTextContent('activating');
	await expect.element(toggle).toBeEnabled();

	await toggle.click();
	expect(setPluginEnabled).toHaveBeenLastCalledWith('slow', false);
	await expect.element(screen.getByTestId('plugin-status-slow')).toHaveTextContent('disabled');
	await expect.element(toggle).not.toBeChecked();
});

test('register_settings_rows_handle_updates_values_in_place_without_remounting', async () => {
	const info: PluginInfo = {
		id: 'hello',
		name: 'Hello',
		enabled: true,
		status: 'active',
		main: 'main.js'
	};
	const runtime = new PluginRuntime(info);
	plugins.runtimes.set('hello', runtime);
	const handle = runtime.registerSettings({
		rows: [
			{
				key: 'greeting',
				type: 'text',
				label: 'Greeting',
				value: 'Hello',
				onChange: () => {}
			},
			{
				key: 'count',
				type: 'number',
				label: 'Count',
				value: 2,
				min: 1,
				max: 5,
				onChange: () => {}
			}
		]
	});

	const screen = await render(PluginSettingsPage, { plugin: info });
	const greeting = screen.getByRole('textbox', { name: 'Greeting' });
	const count = screen.getByRole('spinbutton', { name: 'Count' });
	await expect.element(greeting).toHaveValue('Hello');
	const inputNode = greeting.element();

	await count.fill('9');
	await userEvent.keyboard('{Tab}');
	await expect.element(screen.getByRole('alert')).toHaveTextContent('Enter a number from 1 to 5');

	handle.update({
		rows: [
			{
				key: 'greeting',
				type: 'text',
				label: 'Greeting',
				value: 'Updated in place',
				onChange: () => {}
			},
			{
				key: 'count',
				type: 'number',
				label: 'Count',
				value: 2,
				min: 1,
				max: 5,
				onChange: () => {}
			}
		]
	});
	await expect.element(greeting).toHaveValue('Updated in place');
	expect(greeting.element()).toBe(inputNode);
	await expect.element(screen.getByRole('alert')).toHaveTextContent('Enter a number from 1 to 5');

	handle.dispose();
	await expect.element(screen.getByText('No settings available')).toBeVisible();
});
