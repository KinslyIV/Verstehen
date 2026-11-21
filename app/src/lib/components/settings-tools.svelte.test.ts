import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { userEvent } from 'vitest/browser';
import {
	getSettings,
	saveSettings,
	getDemoBrowser,
	browserDownload,
	getSearchKeys,
	setSearchKey,
	type Settings,
	type BrowserDownloadProgress
} from '#lib/api/client.js';
import SettingsTools from './settings-tools.svelte';

vi.mock('#lib/api/client.js', () => ({
	getSettings: vi.fn(),
	openExternal: vi.fn(),
	saveSettings: vi.fn(),
	getDemoBrowser: vi.fn(),
	browserDownload: vi.fn(),
	getSearchKeys: vi.fn(),
	setSearchKey: vi.fn()
}));
beforeEach(() => {
	vi.clearAllMocks();
	const settings: Settings = {
		worker_request_concurrency: 3,
		demo_browser: null,
		search_engine: 'native',
		background: { chatgpt: false, claude_code: true }
	};
	vi.mocked(getSettings).mockImplementation(async () => settings);
	vi.mocked(saveSettings).mockImplementation(async (next) => {
		Object.assign(settings, next);
		return next;
	});
	vi.mocked(getDemoBrowser).mockResolvedValue({ path: null, source: null });
	vi.mocked(browserDownload).mockResolvedValue({ state: 'idle' });
	vi.mocked(getSearchKeys).mockResolvedValue({
		tavily: { present: false, source: 'none' },
		brave: { present: false, source: 'none' },
		effective_engine: null
	});
});

test('concurrency rejects invalid drafts and commits on Enter and blur while preserving settings', async () => {
	const screen = await render(SettingsTools);
	const input = screen.getByRole('spinbutton', { name: 'Concurrent worker requests' });
	await expect.element(input).toHaveValue(3);
	await input.fill('1.5');
	await userEvent.keyboard('{Enter}');
	await expect
		.element(screen.getByRole('alert'))
		.toHaveTextContent('Enter a positive, safely representable whole number.');
	expect(saveSettings).not.toHaveBeenCalled();
	await input.fill('6');
	await userEvent.keyboard('{Enter}');
	await expect
		.poll(() => vi.mocked(saveSettings).mock.calls.at(-1)?.[0].worker_request_concurrency)
		.toBe(6);
	await expect.element(input).toBeEnabled();
	await input.fill('');
	await screen.getByRole('heading', { name: 'Background tools' }).click();
	await expect
		.poll(() => vi.mocked(saveSettings).mock.calls.at(-1)?.[0].worker_request_concurrency)
		.toBeNull();
	expect(vi.mocked(saveSettings).mock.calls.at(-1)?.[0].background?.chatgpt).toBe(false);
});

test('download starts, shows progress, fails, retries, and hides its button when a browser is found', async () => {
	let progress: BrowserDownloadProgress = { state: 'idle' };
	vi.mocked(browserDownload).mockImplementation(async (start) => {
		if (start) progress = { state: 'downloading', percent: 20, message: 'Downloading Chromium' };
		return progress;
	});
	const screen = await render(SettingsTools);
	const button = screen.getByRole('button', { name: 'Download Chromium for demos' });
	await expect.element(button).toBeEnabled();
	await button.click();
	await expect.element(button).toBeDisabled();
	await expect
		.element(screen.getByRole('progressbar', { name: 'Chromium download' }))
		.toHaveValue(20);
	progress = { state: 'failed', error: 'Fake download failure' };
	await expect.element(screen.getByRole('alert')).toHaveTextContent('Fake download failure');
	await expect.element(button).toBeEnabled();
	await button.click();
	vi.mocked(getDemoBrowser).mockResolvedValue({ path: '/tmp/demo-browser', source: 'downloaded' });
	progress = { state: 'complete', percent: 100 };
	await expect.element(screen.getByText('Chromium installed.')).toBeVisible();
	await expect.element(button).not.toBeInTheDocument();
	await expect.element(screen.getByText('/tmp/demo-browser · downloaded')).toBeVisible();
});

test('environment keys are masked and read only, and missing selected keys show the fallback', async () => {
	vi.mocked(getSettings).mockResolvedValue({ search_engine: 'tavily' });
	vi.mocked(getSearchKeys).mockResolvedValue({
		tavily: { present: false, source: 'none' },
		brave: { present: true, source: 'env', masked: '…abcd (24 chars)' },
		effective_engine: 'brave'
	});
	const screen = await render(SettingsTools);
	await expect.element(screen.getByText('Key missing, using Brave Search.')).toBeVisible();
	await expect.element(screen.getByLabelText('Brave Search', { exact: true })).toBeDisabled();
	await expect
		.element(screen.getByRole('button', { name: 'Clear Brave Search key' }))
		.toBeDisabled();
	await expect.element(screen.getByText('…abcd (24 chars) · from environment')).toBeVisible();
	expect(setSearchKey).not.toHaveBeenCalled();
});
