import { expect, test } from 'vitest';
import { pickModel, cycleLevel, setupStage, slotsComplete } from './picks';
import { testCatalog, mainPick } from './test-fixtures';
const models = testCatalog.accounts[0].models;
test('switching_model_keeps_a_supported_level_and_replaces_an_unsupported_level', () => {
	expect(pickModel('fake', models[0], { ...mainPick, thinking_level: 'high' }).thinking_level).toBe(
		'high'
	);
	expect(pickModel('fake', models[1], mainPick).thinking_level).toBe('low');
	expect(
		pickModel('fake', { ...models[1], thinking_levels: [], default_thinking_level: null }, mainPick)
			.thinking_level
	).toBeNull();
});
test('thinking_cycle_wraps_from_the_last_level_to_the_first', () => {
	expect(cycleLevel({ ...mainPick, thinking_level: 'high' }, models[0]).thinking_level).toBe('low');
	expect(cycleLevel(mainPick, models[0]).thinking_level).toBe('high');
});
test('setup_waits_for_catalog_then_connection_then_requires_all_three_slots', () => {
	expect(setupStage(undefined)).toBe('loading');
	expect(setupStage({ accounts: [], slots: {} })).toBe('connect');
	expect(setupStage(testCatalog)).toBe('models');
	const offline = structuredClone(testCatalog);
	offline.accounts[0].models = [];
	offline.accounts[0].refresh_error = 'ChatGPT could not be reached.';
	expect(setupStage(offline)).toBe('failed');
	expect(slotsComplete({ strong: mainPick, cheap: mainPick })).toBe(false);
	expect(slotsComplete(testCatalog.slots)).toBe(true);
});
