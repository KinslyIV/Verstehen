import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import * as api from '#lib/api/client.js';
import { live } from '#lib/api/live.svelte.js';
import SettingsAccounts from './settings-accounts.svelte';
import SettingsConnection from './settings-connection.svelte';
import SettingsGraph from './settings-graph.svelte';
import SettingsLesson from './settings-lesson.svelte';
import SettingsModels from './settings-models.svelte';
import SettingsTools from './settings-tools.svelte';

const { mode } = vi.hoisted(() => ({ mode: { current: 'remote' as 'remote' | 'sidecar' } }));
vi.mock('#lib/api/connection.js', () => ({
	clientMode: () => mode.current,
	loadConnection: async () => ({ server_url: 'http://100.64.0.7:8420', device_id: 'device-1' })
}));
vi.mock('./model-controls.svelte', () => ({ default: () => {} }));
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getSettings: vi.fn(),
	saveSettings: vi.fn(),
	getModels: vi.fn(),
	refreshModels: vi.fn(),
	listChatGPTAccounts: vi.fn(),
	getClaudeCode: vi.fn(),
	getOwnDeviceName: vi.fn(),
	getSearchKeys: vi.fn(),
	health: vi.fn(),
	getDemoBrowser: vi.fn(),
	browserDownload: vi.fn(),
	streamNotifications: vi.fn()
}));

const offline = () => new TypeError('Failed to fetch');
const stored = {
	worker_request_concurrency: 3,
	compaction_limit: 5000,
	quizzing: 'choice'
} as const;

/** The first stream attempt fails as an outage would; the next one opens. */
function streamFailsOnce() {
	vi.mocked(api.streamNotifications)
		.mockReset()
		.mockRejectedValueOnce(offline())
		.mockImplementation(async (_receive, signal, opened) => {
			opened?.();
			await new Promise<void>((done) => signal.addEventListener('abort', () => done()));
		});
}

async function connectionReturns() {
	await vi.waitFor(() => expect(live.reconnecting).toBe(true));
	live.resume();
}

beforeEach(() => {
	vi.spyOn(live, 'wait').mockImplementation(
		(_attempt, signal) =>
			new Promise<void>((done) => {
				const finish = () => {
					stopOnResume();
					signal.removeEventListener('abort', finish);
					done();
				};
				const stopOnResume = live.onResume(finish);
				signal.addEventListener('abort', finish);
			})
	);
	mode.current = 'remote';
	streamFailsOnce();
	vi.mocked(api.getSettings).mockReset().mockResolvedValue(stored);
	vi.mocked(api.saveSettings).mockReset();
	vi.mocked(api.health).mockReset().mockResolvedValue({ status: 'ok' });
	vi.mocked(api.getModels).mockReset().mockResolvedValue({ accounts: [], slots: {} });
	vi.mocked(api.refreshModels).mockReset().mockResolvedValue();
	vi.mocked(api.listChatGPTAccounts).mockReset().mockResolvedValue([]);
	vi.mocked(api.getClaudeCode)
		.mockReset()
		.mockResolvedValue({ state: 'tested', version: '2.1.327' } as api.BinaryStatus);
	vi.mocked(api.getOwnDeviceName).mockReset().mockResolvedValue('Pixel');
	vi.mocked(api.getSearchKeys)
		.mockReset()
		.mockResolvedValue({
			effective_engine: 'native',
			tavily: { present: false, source: 'none' },
			brave: { present: false, source: 'none' }
		});
	vi.mocked(api.getDemoBrowser).mockReset().mockResolvedValue({ path: null, source: null });
	vi.mocked(api.browserDownload).mockReset().mockResolvedValue({ state: 'idle' });
});

afterEach(() => vi.restoreAllMocks());

test('lesson_loads_once_the_connection_returns_after_a_failed_first_read', async () => {
	vi.mocked(api.getSettings).mockRejectedValueOnce(offline());
	const screen = await render(SettingsLesson);
	await expect.element(screen.getByRole('alert')).toHaveTextContent('Failed to fetch');
	const limit = screen.getByRole('spinbutton', { name: 'Compaction limit' });
	await expect.element(limit).toBeDisabled();

	await connectionReturns();
	await expect.element(limit).toBeEnabled();
	await expect.element(limit).toHaveValue(5000);
	await expect.element(screen.getByRole('alert')).not.toBeInTheDocument();
});

test('a_loaded_lesson_keeps_the_typed_edit_and_is_not_read_again_on_return', async () => {
	const screen = await render(SettingsLesson);
	const limit = screen.getByRole('spinbutton', { name: 'Compaction limit' });
	await expect.element(limit).toBeEnabled();
	await limit.fill('9000');

	await connectionReturns();
	await vi.waitFor(() => expect(api.streamNotifications).toHaveBeenCalledTimes(2));
	await expect.element(limit).toHaveValue(9000);
	expect(api.getSettings).toHaveBeenCalledTimes(1);
});

test('graph_settings_load_once_the_connection_returns_after_a_failed_first_read', async () => {
	vi.mocked(api.getSettings).mockRejectedValueOnce(offline());
	const screen = await render(SettingsGraph);
	await expect.element(screen.getByRole('alert')).toHaveTextContent('Failed to fetch');

	await connectionReturns();
	await expect
		.element(screen.getByRole('spinbutton', { name: 'Extraction chunk budget' }))
		.toBeEnabled();
	await expect.element(screen.getByRole('alert')).not.toBeInTheDocument();
});

test('models_load_once_the_connection_returns_after_a_failed_first_read', async () => {
	vi.mocked(api.getModels).mockRejectedValueOnce(offline()).mockRejectedValueOnce(offline());
	vi.mocked(api.refreshModels).mockRejectedValueOnce(offline());
	const screen = await render(SettingsModels);
	await expect.element(screen.getByRole('alert')).toHaveTextContent('Failed to fetch');

	await connectionReturns();
	await expect.element(screen.getByText('Main', { exact: true })).toBeVisible();
	await expect.element(screen.getByRole('alert')).not.toBeInTheDocument();
});

test('accounts_load_once_the_connection_returns_after_a_failed_first_read', async () => {
	vi.mocked(api.listChatGPTAccounts).mockRejectedValueOnce(offline());
	const screen = await render(SettingsAccounts);
	await expect.element(screen.getByText('Failed to fetch')).toBeVisible();

	await connectionReturns();
	await expect.element(screen.getByText('Failed to fetch')).not.toBeInTheDocument();
	await expect.element(screen.getByRole('region', { name: 'Claude Code account' })).toBeVisible();
});

test('tools_load_once_the_connection_returns_after_a_failed_first_read', async () => {
	vi.mocked(api.getSettings).mockRejectedValueOnce(offline());
	const screen = await render(SettingsTools);
	await expect.element(screen.getByText('Failed to fetch')).toBeVisible();

	await connectionReturns();
	await expect.element(screen.getByText('Failed to fetch')).not.toBeInTheDocument();
	await expect.element(screen.getByRole('spinbutton')).toHaveValue(3);
});

test('the_device_name_loads_once_the_connection_returns_after_a_failed_first_read', async () => {
	vi.mocked(api.getOwnDeviceName).mockRejectedValueOnce(offline());
	const screen = await render(SettingsConnection);
	await expect.element(screen.getByTestId('connection-device')).toHaveTextContent('…');

	await connectionReturns();
	await expect.element(screen.getByTestId('connection-device')).toHaveTextContent('Pixel');
});

test('the_desktop_never_opens_a_recovery_stream_for_a_settings_section', async () => {
	mode.current = 'sidecar';
	const screen = await render(SettingsLesson);
	await expect.element(screen.getByRole('spinbutton', { name: 'Compaction limit' })).toBeEnabled();
	expect(api.streamNotifications).not.toHaveBeenCalled();
});
