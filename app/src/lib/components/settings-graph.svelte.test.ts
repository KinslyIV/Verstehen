import { expect, test, vi } from 'vitest';
import { userEvent } from 'vitest/browser';
import { render } from 'vitest-browser-svelte';
import { getSettings, saveSettings, type Settings } from '#lib/api/client.js';
import SettingsGraph from './settings-graph.svelte';

vi.mock('#lib/api/client.js', () => ({ getSettings: vi.fn(), saveSettings: vi.fn() }));

const base: Settings = {
	models: { strong: { account: 'fake', model: 'fake' } },
	quizzing: 'choice'
};

async function renderGraph(patch: Partial<Settings> = {}) {
	vi.mocked(getSettings)
		.mockReset()
		.mockResolvedValue({ ...base, ...patch });
	vi.mocked(saveSettings)
		.mockReset()
		.mockImplementation(async (settings) => settings);
	const screen = await render(SettingsGraph);
	const field = screen.getByRole('spinbutton', { name: 'Extraction chunk budget' });
	await expect.element(field).toBeEnabled();
	return { screen, field };
}

const lastSaved = () => vi.mocked(saveSettings).mock.calls.at(-1)?.[0];

test('graph_switches_write_their_own_setting_and_keep_the_others', async () => {
	const { screen } = await renderGraph();
	await screen.getByRole('switch', { name: 'extraction enabled' }).click();
	await expect.poll(() => lastSaved()?.graph?.enabled).toBe(false);
	expect(lastSaved()?.graph?.rendering).toBe(true);
	await expect.element(screen.getByRole('switch', { name: 'graph tools' })).toBeDisabled();
	await expect.element(screen.getByText('Graph is disabled')).toBeVisible();
});

test('prober_graph_tools_switch_writes_the_agent_setting', async () => {
	const { screen } = await renderGraph();
	await screen.getByRole('switch', { name: 'graph tools' }).click();
	await expect.poll(() => lastSaved()?.agent?.graph_tools).toBe(false);
});

test('chunk_budget_commits_on_enter_and_blur_and_raises_to_the_floor', async () => {
	const { screen, field } = await renderGraph();
	await expect.element(field).toHaveAttribute('placeholder', '4096');
	await field.fill('6000');
	await userEvent.keyboard('{Enter}');
	await expect.poll(() => lastSaved()?.graph?.extraction_chunk_tokens).toBe(6000);
	await field.fill('100');
	await userEvent.click(screen.getByText('Extraction chunk budget'));
	await expect.poll(() => lastSaved()?.graph?.extraction_chunk_tokens).toBe(500);
	await expect.element(field).toHaveValue(500);
});

test('chunk_budget_empty_means_default_and_invalid_input_is_not_saved', async () => {
	const { screen, field } = await renderGraph({
		graph: { enabled: true, rendering: true, extraction_chunk_tokens: 9000 }
	});
	await field.fill('');
	await userEvent.keyboard('{Enter}');
	await expect.poll(() => lastSaved()?.graph?.extraction_chunk_tokens).toBe(4096);
	vi.mocked(saveSettings).mockClear();
	await field.fill('-5');
	await userEvent.click(screen.getByText('Extraction chunk budget'));
	expect(saveSettings).not.toHaveBeenCalled();
});
