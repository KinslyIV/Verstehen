import { expect, test, vi } from 'vitest';
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
