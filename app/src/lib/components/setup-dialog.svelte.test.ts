import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from 'vitest/browser';
import * as api from '#lib/api/client.js';
import { testCatalog, testSettings } from '#lib/models/test-fixtures.js';
import NewSession from './new-session.svelte';
import SetupDialog from './setup-dialog.svelte';
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getModels: vi.fn(),
	getSettings: vi.fn(),
	saveSettings: vi.fn(),
	createSession: vi.fn()
}));
beforeEach(() => {
	vi.clearAllMocks();
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
test('connection_stage_advances_when_an_account_becomes_ready_and_is_closable', async () => {
	vi.mocked(api.getModels).mockResolvedValueOnce({ accounts: [], slots: {} });
	const close = vi.fn();
	await render(SetupDialog, { onclose: close, ondone: vi.fn() });
	await expect.element(page.getByRole('heading', { name: 'Connect a provider' })).toBeVisible();
	await expect.element(page.getByRole('button', { name: 'Open Settings' })).toBeVisible();
	await expect.element(page.getByRole('tab', { name: 'Main', exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Cancel', exact: true }).click();
	expect(close).toHaveBeenCalledOnce();
});
