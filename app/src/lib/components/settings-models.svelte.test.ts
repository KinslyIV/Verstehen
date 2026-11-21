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
	vi.mocked(api.getModels).mockResolvedValue(structuredClone(testCatalog));
});
test('opening_models_settings_forces_one_refresh_before_the_controls_read_the_catalog', async () => {
	await render(SettingsModels);
	await expect
		.element(page.getByRole('button', { name: 'Choose Cheap model', exact: true }))
		.toBeVisible();
	const calls = vi.mocked(api.getModels).mock.calls;
	expect(calls[0]).toEqual([{ refresh: true }]);
	expect(calls.filter(([options]) => options?.refresh)).toHaveLength(1);
	expect(calls.length).toBeGreaterThan(1);
});
