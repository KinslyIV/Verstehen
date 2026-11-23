import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from 'vitest/browser';
import * as api from '#lib/api/client.js';
import { models } from '#lib/models/catalog.svelte.js';
import { testCatalog, testSettings, mainPick } from '#lib/models/test-fixtures.js';
import ModelControls from './model-controls.svelte';
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getModels: vi.fn(),
	refreshModels: vi.fn(),
	getSettings: vi.fn(),
	saveSettings: vi.fn(),
	setDefaultModel: vi.fn(),
	setSessionModel: vi.fn()
}));
beforeEach(() => {
	vi.clearAllMocks();
	models.reset();
	vi.mocked(api.refreshModels).mockResolvedValue(undefined);
	vi.mocked(api.getModels).mockResolvedValue(structuredClone(testCatalog));
	vi.mocked(api.getSettings).mockResolvedValue(structuredClone(testSettings));
	vi.mocked(api.saveSettings).mockResolvedValue(testSettings);
});
test('main_pick_is_local_and_only_set_as_default_saves_the_strong_slot', async () => {
	const onpick = vi.fn();
	const screen = await render(ModelControls, { pick: mainPick, onpick });
	await screen.getByRole('button', { name: 'Choose model', exact: true }).click();
	await page.getByRole('button', { name: 'Scripted title', exact: true }).click();
	expect(onpick).toHaveBeenCalledWith({
		account: 'fake',
		model: 'fake-title',
		thinking_level: 'low'
	});
	expect(api.setDefaultModel).not.toHaveBeenCalled();
	expect(api.saveSettings).not.toHaveBeenCalled();
	await screen.rerender({ pick: { account: 'fake', model: 'fake-title', thinking_level: 'low' } });
	await page.getByRole('button', { name: 'Set as default', exact: true }).click();
	await expect.poll(() => vi.mocked(api.setDefaultModel).mock.calls.length).toBe(1);
	expect(api.setDefaultModel).toHaveBeenCalledWith({
		account: 'fake',
		model: 'fake-title',
		thinking_level: 'low'
	});
});
test('cheap_and_vision_tabs_write_the_global_slot_and_vision_filters_text_models', async () => {
	const screen = await render(ModelControls, { pick: mainPick, onpick: vi.fn() });
	await screen.getByRole('button', { name: 'Choose model', exact: true }).click();
	await page.getByRole('tab', { name: 'Cheap', exact: true }).click();
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await expect.poll(() => vi.mocked(api.saveSettings).mock.calls.length).toBe(1);
	expect(vi.mocked(api.saveSettings).mock.calls[0][0].models?.cheap?.model).toBe('fake');
	expect(vi.mocked(api.saveSettings).mock.calls[0][0].models?.strong).toEqual(mainPick);
	await page.getByRole('tab', { name: 'Vision', exact: true }).click();
	await expect
		.element(page.getByRole('button', { name: 'Scripted title', exact: true }))
		.not.toBeInTheDocument();
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await expect.poll(() => vi.mocked(api.saveSettings).mock.calls.length).toBe(2);
	expect(vi.mocked(api.saveSettings).mock.calls[1][0].models?.vision?.model).toBe('fake');
});
test('shift_tab_wraps_the_session_level_without_changing_defaults', async () => {
	const onpick = vi.fn();
	await render(ModelControls, {
		pick: { ...mainPick, thinking_level: 'high' },
		sessionId: 'one',
		onpick
	});
	await expect.poll(() => vi.mocked(api.getModels).mock.calls.length).toBe(1);
	await userEvent.keyboard('{Shift>}{Tab}{/Shift}');
	await expect.poll(() => onpick.mock.calls.length).toBe(1);
	expect(api.setSessionModel).toHaveBeenCalledWith('one', { ...mainPick, thinking_level: 'low' });
	expect(api.setDefaultModel).not.toHaveBeenCalled();
});

test('an_in_flight_slot_pick_keeps_its_original_tab_target', async () => {
	let release!: (settings: api.Settings) => void;
	vi.mocked(api.getSettings).mockImplementationOnce(
		() => new Promise((resolve) => (release = resolve))
	);
	const screen = await render(ModelControls, { pick: mainPick, onpick: vi.fn() });
	await screen.getByRole('button', { name: 'Choose model', exact: true }).click();
	await page.getByRole('tab', { name: 'Cheap', exact: true }).click();
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await expect.poll(() => vi.mocked(api.getSettings).mock.calls.length).toBe(1);
	await page.getByRole('tab', { name: 'Vision', exact: true }).click();
	release(testSettings);
	await expect.poll(() => vi.mocked(api.saveSettings).mock.calls.length).toBe(1);
	expect(vi.mocked(api.saveSettings).mock.calls[0][0].models?.cheap?.model).toBe('fake');
	expect(vi.mocked(api.saveSettings).mock.calls[0][0].models?.vision).toEqual(mainPick);
});

test('a_settings_picker_has_no_slot_tabs_and_writes_only_its_slot', async () => {
	vi.mocked(api.getModels).mockResolvedValue(structuredClone(testCatalog));
	const screen = await render(ModelControls, {
		onpick: vi.fn(),
		initialTab: 'cheap',
		tabs: false,
		shortcuts: false,
		label: 'Choose Cheap model'
	});
	await screen.getByRole('button', { name: 'Choose Cheap model' }).click();
	await expect.element(page.getByRole('tab')).not.toBeInTheDocument();
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await expect.poll(() => vi.mocked(api.saveSettings).mock.calls.length).toBe(1);
	const saved = vi.mocked(api.saveSettings).mock.calls[0][0].models;
	expect(saved?.cheap?.model).toBe('fake');
	expect(saved?.strong).toEqual(mainPick);
});

test('saved_models_stay_selectable_with_the_failure_noted_when_a_refresh_fails', async () => {
	const catalog = structuredClone(testCatalog);
	catalog.accounts[0].refresh_error = 'ChatGPT could not be reached. Try again.';
	vi.mocked(api.getModels).mockResolvedValue(catalog);
	const onpick = vi.fn();
	const screen = await render(ModelControls, { pick: mainPick, onpick });
	await screen.getByRole('button', { name: 'Choose model', exact: true }).click();
	await expect
		.element(page.getByRole('status'))
		.toHaveTextContent('Showing saved models. ChatGPT could not be reached. Try again.');
	await page.getByRole('button', { name: 'Scripted title', exact: true }).click();
	expect(onpick).toHaveBeenCalledOnce();
});

test('opening_the_menu_refreshes_the_accounts_without_replacing_the_saved_slots', async () => {
	vi.mocked(api.getModels).mockResolvedValue(structuredClone(testCatalog));
	const screen = await render(ModelControls, { onpick: vi.fn() });
	await expect
		.element(screen.getByRole('button', { name: 'Choose model', exact: true }))
		.toHaveTextContent('Scripted teacher · Medium');
	await screen.getByRole('button', { name: 'Choose model', exact: true }).click();
	await expect.poll(() => vi.mocked(api.refreshModels).mock.calls.length).toBe(1);
	expect(api.refreshModels).toHaveBeenCalledWith(false);
});
