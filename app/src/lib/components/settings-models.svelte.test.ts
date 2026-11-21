import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from 'vitest/browser';
import * as api from '#lib/api/client.js';
import { testCatalog } from '#lib/models/test-fixtures.js';
import SettingsModels from './settings-models.svelte';
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getModels: vi.fn()
}));
beforeEach(() => {
	vi.clearAllMocks();
});
test('pending_refresh_shows_loading_and_mounts_no_controls', async () => {
	vi.mocked(api.getModels).mockReturnValue(new Promise(() => {}));
	await render(SettingsModels);
	await expect.element(page.getByText('Loading models…')).toBeVisible();
	await expect
		.element(page.getByRole('button', { name: 'Choose Main model', exact: true }))
		.not.toBeInTheDocument();
});
test('rejected_refresh_shows_the_error_and_controls_do_not_refetch', async () => {
	vi.mocked(api.getModels).mockRejectedValue(new Error('ChatGPT could not be reached'));
	await render(SettingsModels);
	await expect.element(page.getByRole('alert')).toHaveTextContent('ChatGPT could not be reached');
	await expect
		.element(page.getByRole('button', { name: 'Choose Main model', exact: true }))
		.not.toBeInTheDocument();
	expect(api.getModels).toHaveBeenCalledTimes(1);
});
test('opening_models_settings_refreshes_once_and_the_controls_reuse_that_catalog', async () => {
	vi.mocked(api.getModels).mockResolvedValue(structuredClone(testCatalog));
	await render(SettingsModels);
	for (const name of ['Main', 'Cheap', 'Vision'])
		await expect
			.element(page.getByRole('button', { name: `Choose ${name} model`, exact: true }))
			.toBeVisible();
	expect(api.getModels).toHaveBeenCalledTimes(1);
	expect(api.getModels).toHaveBeenCalledWith({ refresh: true });
});
