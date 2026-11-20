import { expect, test, vi } from 'vitest';
import { userEvent } from 'vitest/browser';
import { render } from 'vitest-browser-svelte';
import { getSettings, saveSettings, type Settings } from '#lib/api/client.js';
import SettingsLesson from './settings-lesson.svelte';

vi.mock('#lib/api/client.js', () => ({ getSettings: vi.fn(), saveSettings: vi.fn() }));

test('quizzing_control_writes_quizzing_and_preserves_the_other_settings', async () => {
	const current: Settings = {
		models: { strong: { account: 'fake', model: 'fake' } },
		background: { chatgpt: false, claude_code: true },
		quizzing: 'choice'
	};
	vi.mocked(getSettings).mockResolvedValue(current);
	vi.mocked(saveSettings).mockImplementation(async (settings) => settings);
	const screen = await render(SettingsLesson);
	await expect
		.element(screen.getByRole('button', { name: 'Multiple choice' }))
		.toHaveAttribute('aria-pressed', 'true');
	await screen.getByRole('button', { name: 'Free recall' }).click();
	await expect
		.element(screen.getByRole('button', { name: 'Free recall' }))
		.toHaveAttribute('aria-pressed', 'true');
	expect(saveSettings).toHaveBeenCalledWith({ ...current, quizzing: 'free' });
});

const lessonSettings: Settings = {
	models: { strong: { account: 'fake', model: 'fake' } },
	background: { chatgpt: false, claude_code: true },
	quizzing: 'choice'
};

async function renderLimit(compaction_limit?: number | null) {
	vi.mocked(getSettings)
		.mockReset()
		.mockResolvedValue({ ...lessonSettings, compaction_limit });
	vi.mocked(saveSettings)
		.mockReset()
		.mockImplementation(async (settings) => settings);
	const screen = await render(SettingsLesson);
	const field = screen.getByRole('spinbutton', { name: 'Compaction limit' });
	await expect.element(field).toBeEnabled();
	return { screen, field };
}

test('compaction_limit_commits_on_enter_and_blur_and_raises_to_the_floor', async () => {
	const { screen, field } = await renderLimit();
	await expect.element(field).toHaveAttribute('placeholder', '150000');
	await field.fill('200000');
	await userEvent.keyboard('{Enter}');
	await expect
		.poll(() => vi.mocked(saveSettings).mock.calls.at(-1)?.[0].compaction_limit)
		.toBe(200_000);
	await field.fill('1000');
	await userEvent.click(screen.getByText('Compaction limit'));
	await expect
		.poll(() => vi.mocked(saveSettings).mock.calls.at(-1)?.[0].compaction_limit)
		.toBe(32_000);
	await expect.element(field).toHaveValue(32_000);
});

test('compaction_limit_empty_means_default_and_invalid_input_is_not_saved', async () => {
	const { screen, field } = await renderLimit(60_000);
	await field.fill('');
	await userEvent.keyboard('{Enter}');
	await expect
		.poll(() => vi.mocked(saveSettings).mock.calls.at(-1)?.[0].compaction_limit)
		.toBeNull();
	vi.mocked(saveSettings).mockClear();
	await field.fill('-5');
	await userEvent.click(screen.getByText('Compaction limit'));
	expect(saveSettings).not.toHaveBeenCalled();
});
