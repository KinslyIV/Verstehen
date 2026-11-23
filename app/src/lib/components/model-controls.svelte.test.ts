import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from 'vitest/browser';
import * as api from '#lib/api/client.js';
import { models } from '#lib/models/catalog.svelte.js';
import { testCatalog, mainPick } from '#lib/models/test-fixtures.js';
import ModelControls from './model-controls.svelte';
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getModels: vi.fn(),
	refreshModels: vi.fn(),
	setModelSlot: vi.fn(),
	setDefaultModel: vi.fn(),
	setSessionModel: vi.fn()
}));
beforeEach(() => {
	vi.clearAllMocks();
	models.reset();
	vi.mocked(api.refreshModels).mockResolvedValue(undefined);
	vi.mocked(api.getModels).mockResolvedValue(structuredClone(testCatalog));
	vi.mocked(api.setModelSlot).mockResolvedValue(mainPick);
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
	expect(api.setModelSlot).not.toHaveBeenCalled();
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
	await expect.poll(() => vi.mocked(api.setModelSlot).mock.calls.length).toBe(1);
	expect(api.setModelSlot).toHaveBeenLastCalledWith(
		'cheap',
		expect.objectContaining({ model: 'fake' })
	);
	await page.getByRole('tab', { name: 'Vision', exact: true }).click();
	await expect
		.element(page.getByRole('button', { name: 'Scripted title', exact: true }))
		.not.toBeInTheDocument();
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await expect.poll(() => vi.mocked(api.setModelSlot).mock.calls.length).toBe(2);
	expect(api.setModelSlot).toHaveBeenLastCalledWith(
		'vision',
		expect.objectContaining({ model: 'fake' })
	);
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
	let release!: (pick: api.ModelPick) => void;
	vi.mocked(api.setModelSlot).mockImplementationOnce(
		() => new Promise((resolve) => (release = resolve))
	);
	const screen = await render(ModelControls, { pick: mainPick, onpick: vi.fn() });
	await screen.getByRole('button', { name: 'Choose model', exact: true }).click();
	await page.getByRole('tab', { name: 'Cheap', exact: true }).click();
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await expect.poll(() => vi.mocked(api.setModelSlot).mock.calls.length).toBe(1);
	await page.getByRole('tab', { name: 'Vision', exact: true }).click();
	release(mainPick);
	expect(api.setModelSlot).toHaveBeenCalledExactlyOnceWith(
		'cheap',
		expect.objectContaining({ model: 'fake' })
	);
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
	await expect.poll(() => vi.mocked(api.setModelSlot).mock.calls.length).toBe(1);
	expect(api.setModelSlot).toHaveBeenCalledExactlyOnceWith(
		'cheap',
		expect.objectContaining({ model: 'fake' })
	);
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

test('opening_the_menu_rereads_the_saved_catalog_without_contacting_accounts', async () => {
	vi.mocked(api.getModels).mockResolvedValue(structuredClone(testCatalog));
	const screen = await render(ModelControls, { onpick: vi.fn() });
	await expect
		.element(screen.getByRole('button', { name: 'Choose model', exact: true }))
		.toHaveTextContent('Scripted teacher · Medium');
	const reads = vi.mocked(api.getModels).mock.calls.length;
	await screen.getByRole('button', { name: 'Choose model', exact: true }).click();
	await expect.poll(() => vi.mocked(api.getModels).mock.calls.length).toBeGreaterThan(reads);
	expect(api.refreshModels).not.toHaveBeenCalled();
});

test('the_thinking_slider_steps_through_the_models_own_levels_and_reports_the_current_one', async () => {
	const onpick = vi.fn();
	const screen = await render(ModelControls, { pick: mainPick, onpick });
	await screen.getByRole('button', { name: 'Choose model', exact: true }).click();
	const slider = page.getByRole('slider', { name: 'Thinking level' });
	await expect.element(slider).toHaveAttribute('aria-valuetext', 'medium');
	(slider.element() as HTMLElement).focus();
	await userEvent.keyboard('{ArrowRight}');
	expect(onpick).toHaveBeenLastCalledWith({ ...mainPick, thinking_level: 'high' });
});

test('a_model_without_thinking_levels_keeps_the_strip_and_says_so', async () => {
	const catalog = structuredClone(testCatalog);
	catalog.accounts[0].models[0].thinking_levels = [];
	vi.mocked(api.getModels).mockResolvedValue(catalog);
	const screen = await render(ModelControls, { pick: mainPick, onpick: vi.fn() });
	await screen.getByRole('button', { name: 'Choose model', exact: true }).click();
	await expect.element(page.getByText('No thinking levels')).toBeVisible();
	await expect.element(page.getByRole('slider')).not.toBeInTheDocument();
});
