import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from 'vitest/browser';
import * as api from '#lib/api/client.js';
import { models } from '#lib/models/catalog.svelte.js';
import { testCatalog } from '#lib/models/test-fixtures.js';
import SettingsModels from './settings-models.svelte';
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getModels: vi.fn(),
	refreshModels: vi.fn()
}));
beforeEach(() => {
	vi.clearAllMocks();
	models.reset();
	vi.mocked(api.refreshModels).mockResolvedValue(undefined);
});
test('pending_read_shows_loading_and_mounts_no_controls', async () => {
	vi.mocked(api.getModels).mockReturnValue(new Promise(() => {}));
	await render(SettingsModels);
	await expect.element(page.getByText('Loading models…')).toBeVisible();
	await expect
		.element(page.getByRole('button', { name: 'Choose Main model', exact: true }))
		.not.toBeInTheDocument();
});
test('rejected_read_shows_the_error_and_mounts_no_controls', async () => {
	vi.mocked(api.getModels).mockRejectedValue(new Error('The sidecar is unreachable'));
	await render(SettingsModels);
	await expect.element(page.getByRole('alert')).toHaveTextContent('The sidecar is unreachable');
	await expect
		.element(page.getByRole('button', { name: 'Choose Main model', exact: true }))
		.not.toBeInTheDocument();
});
test('saved_slots_show_while_the_accounts_are_still_refreshing', async () => {
	vi.mocked(api.getModels).mockResolvedValue(structuredClone(testCatalog));
	vi.mocked(api.refreshModels).mockReturnValue(new Promise(() => {}));
	await render(SettingsModels);
	for (const name of ['Main', 'Cheap', 'Vision'])
		await expect
			.element(page.getByRole('button', { name: `Choose ${name} model`, exact: true }))
			.toBeVisible();
	await expect
		.element(page.getByRole('button', { name: 'Choose Cheap model' }))
		.toHaveTextContent('Scripted title · Low');
	expect(api.refreshModels).toHaveBeenCalledWith(false);
});
test('the_refresh_button_forces_one_refresh_and_reports_the_result', async () => {
	vi.mocked(api.getModels).mockResolvedValue(structuredClone(testCatalog));
	await render(SettingsModels);
	await page.getByRole('button', { name: 'Refresh model lists' }).click();
	await expect.element(page.getByText('Models are up to date.')).toBeVisible();
	expect(api.refreshModels).toHaveBeenLastCalledWith(true);
	expect(vi.mocked(api.refreshModels).mock.calls.filter(([force]) => force)).toHaveLength(1);
});
test('an_unreachable_account_is_named_and_its_saved_models_remain', async () => {
	const stale = structuredClone(testCatalog);
	stale.accounts[0].refresh_error = 'ChatGPT could not be reached. Try again.';
	vi.mocked(api.getModels).mockResolvedValue(stale);
	await render(SettingsModels);
	await page.getByRole('button', { name: 'Refresh model lists' }).click();
	await expect
		.element(page.getByText('Could not reach Scripted model. Saved models are still available.'))
		.toBeVisible();
	await page.getByRole('button', { name: 'Choose Cheap model' }).click();
	await expect.element(page.getByRole('button', { name: 'Scripted teacher' })).toBeVisible();
});
test('a_failed_refresh_request_is_reported_and_the_button_works_again', async () => {
	vi.mocked(api.getModels).mockResolvedValue(structuredClone(testCatalog));
	await render(SettingsModels);
	vi.mocked(api.refreshModels).mockRejectedValueOnce(new Error('HTTP 500'));
	await page.getByRole('button', { name: 'Refresh model lists' }).click();
	await expect.element(page.getByText('Could not refresh: HTTP 500')).toBeVisible();
	await expect.element(page.getByRole('button', { name: 'Refresh model lists' })).toBeEnabled();
});
test('the_settings_pickers_have_no_slot_tabs', async () => {
	vi.mocked(api.getModels).mockResolvedValue(structuredClone(testCatalog));
	await render(SettingsModels);
	await page.getByRole('button', { name: 'Choose Vision model' }).click();
	await expect.element(page.getByRole('tab')).not.toBeInTheDocument();
});
test('only_the_main_picker_offers_set_as_default', async () => {
	vi.mocked(api.getModels).mockResolvedValue(structuredClone(testCatalog));
	await render(SettingsModels);
	await page.getByRole('button', { name: 'Choose Cheap model' }).click();
	await expect
		.element(page.getByRole('button', { name: 'Set as default', exact: true }))
		.not.toBeInTheDocument();
	await userEvent.keyboard('{Escape}');
	await page.getByRole('button', { name: 'Choose Main model' }).click();
	await expect
		.element(page.getByRole('button', { name: 'Set as default', exact: true }))
		.toBeVisible();
});
