import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from 'vitest/browser';
import * as api from '#lib/api/client.js';
import { models } from '#lib/models/catalog.svelte.js';
import { testCatalog, testSettings } from '#lib/models/test-fixtures.js';
import NewSession from './new-session.svelte';
import SetupDialog from './setup-dialog.svelte';
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getModels: vi.fn(),
	refreshModels: vi.fn(),
	getSettings: vi.fn(),
	saveSettings: vi.fn(),
	createSession: vi.fn()
}));
beforeEach(() => {
	vi.clearAllMocks();
	models.reset();
	vi.mocked(api.refreshModels).mockResolvedValue(undefined);
	vi.mocked(api.getModels).mockResolvedValue({ ...structuredClone(testCatalog), slots: {} });
	vi.mocked(api.getSettings).mockResolvedValue({ ...structuredClone(testSettings), models: {} });
	vi.mocked(api.saveSettings).mockResolvedValue(testSettings);
});
test('saving_setup_keeps_the_draft_unsent_and_requires_all_three_slots', async () => {
	const screen = await render(NewSession);
	await screen.getByRole('textbox').fill('Keep this draft');
	await screen.getByRole('button', { name: 'Send', exact: true }).click();
	await expect
		.element(page.getByRole('button', { name: 'Save models', exact: true }))
		.toBeDisabled();
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await page.getByRole('tab', { name: 'Cheap', exact: true }).click();
	await page.getByRole('button', { name: 'Scripted title', exact: true }).click();
	await expect
		.element(page.getByRole('button', { name: 'Save models', exact: true }))
		.toBeDisabled();
	await page.getByRole('tab', { name: 'Vision', exact: true }).click();
	await expect
		.element(page.getByRole('button', { name: 'Scripted title', exact: true }))
		.not.toBeInTheDocument();
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await page.getByRole('button', { name: 'Save models', exact: true }).click();
	await expect.element(screen.getByRole('textbox')).toHaveValue('Keep this draft');
	expect(api.createSession).not.toHaveBeenCalled();
	expect(api.saveSettings).toHaveBeenCalledOnce();
});
test('saving_setup_sends_only_the_model_slots', async () => {
	vi.mocked(api.getSettings).mockResolvedValue({
		...structuredClone(testSettings),
		quizzing: 'free',
		models: {}
	});
	await render(SetupDialog, { onclose: vi.fn(), ondone: vi.fn() });
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await page.getByRole('tab', { name: 'Cheap', exact: true }).click();
	await page.getByRole('button', { name: 'Scripted title', exact: true }).click();
	await page.getByRole('tab', { name: 'Vision', exact: true }).click();
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await page.getByRole('button', { name: 'Save models', exact: true }).click();
	await expect.poll(() => vi.mocked(api.saveSettings).mock.calls.length).toBe(1);
	const body = vi.mocked(api.saveSettings).mock.calls[0][0];
	expect(Object.keys(body)).toEqual(['models']);
});
test('connection_stage_advances_when_an_account_becomes_ready_and_is_closable', async () => {
	let connected = false;
	vi.mocked(api.getModels).mockImplementation(async () =>
		connected ? { ...structuredClone(testCatalog), slots: {} } : { accounts: [], slots: {} }
	);
	const close = vi.fn();
	await render(SetupDialog, { onclose: close, ondone: vi.fn() });
	await expect.element(page.getByRole('heading', { name: 'Connect a provider' })).toBeVisible();
	await expect.element(page.getByRole('button', { name: 'Open Settings' })).toBeVisible();
	connected = true;
	await expect.element(page.getByRole('tab', { name: 'Main', exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Cancel', exact: true }).click();
	expect(close).toHaveBeenCalledOnce();
});

test('an_empty_saved_catalog_waits_for_the_first_refresh_before_asking_to_connect', async () => {
	vi.mocked(api.getModels).mockResolvedValue({ accounts: [], slots: {} });
	let finish!: () => void;
	vi.mocked(api.refreshModels).mockImplementation(
		() => new Promise<void>((resolve) => (finish = resolve))
	);
	await render(SetupDialog, { onclose: vi.fn(), ondone: vi.fn() });
	await expect.element(page.getByText('Loading models…')).toBeVisible();
	await expect
		.element(page.getByRole('heading', { name: 'Connect a provider' }))
		.not.toBeInTheDocument();
	finish();
	await expect.element(page.getByRole('heading', { name: 'Connect a provider' })).toBeVisible();
});
test('saved_models_open_the_slot_choices_without_waiting_for_the_refresh', async () => {
	vi.mocked(api.refreshModels).mockImplementation(() => new Promise(() => {}));
	await render(SetupDialog, { onclose: vi.fn(), ondone: vi.fn() });
	await expect.element(page.getByRole('tab', { name: 'Main', exact: true })).toBeVisible();
});
test('an_account_saved_without_models_waits_for_discovery_and_then_shows_the_models', async () => {
	const waiting = structuredClone(testCatalog);
	waiting.accounts[0].models = [];
	vi.mocked(api.getModels).mockResolvedValue({ ...waiting, slots: {} });
	vi.mocked(api.refreshModels).mockImplementation(() => new Promise(() => {}));
	await render(SetupDialog, { onclose: vi.fn(), ondone: vi.fn() });
	await expect.element(page.getByText('Loading models…')).toBeVisible();
	await expect
		.element(page.getByRole('heading', { name: 'Connect a provider' }))
		.not.toBeInTheDocument();
	vi.mocked(api.getModels).mockResolvedValue({ ...structuredClone(testCatalog), slots: {} });
	await expect.element(page.getByRole('tab', { name: 'Main', exact: true })).toBeVisible();
});
test('an_account_saved_without_models_asks_to_connect_once_discovery_finished', async () => {
	const empty = structuredClone(testCatalog);
	empty.accounts[0].models = [];
	vi.mocked(api.getModels).mockResolvedValue({ ...empty, slots: {} });
	await render(SetupDialog, { onclose: vi.fn(), ondone: vi.fn() });
	await expect.element(page.getByRole('heading', { name: 'Connect a provider' })).toBeVisible();
});
test('a_failed_read_or_refresh_shows_the_error_with_retry_instead_of_the_connect_stage', async () => {
	vi.mocked(api.getModels).mockRejectedValue(new Error('The sidecar is unreachable'));
	await render(SetupDialog, { onclose: vi.fn(), ondone: vi.fn() });
	await expect.element(page.getByText('The sidecar is unreachable')).toBeVisible();
	await expect
		.element(page.getByRole('heading', { name: 'Connect a provider' }))
		.not.toBeInTheDocument();
	vi.mocked(api.getModels).mockResolvedValue({ ...structuredClone(testCatalog), slots: {} });
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect.element(page.getByRole('tab', { name: 'Main', exact: true })).toBeVisible();
});
test('a_failed_refresh_of_an_empty_catalog_asks_to_retry_not_to_connect', async () => {
	vi.mocked(api.getModels).mockResolvedValue({ accounts: [], slots: {} });
	vi.mocked(api.refreshModels).mockRejectedValue(new Error('HTTP 500'));
	await render(SetupDialog, { onclose: vi.fn(), ondone: vi.fn() });
	await expect.element(page.getByText('HTTP 500')).toBeVisible();
	await expect
		.element(page.getByRole('heading', { name: 'Connect a provider' }))
		.not.toBeInTheDocument();
	await expect.element(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
});
