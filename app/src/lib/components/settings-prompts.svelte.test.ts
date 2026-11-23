import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from 'vitest/browser';
import * as api from '#lib/api/client.js';
import SettingsPrompts from './settings-prompts.svelte';

vi.mock('#lib/api/client.js', () => ({
	getPrompts: vi.fn(),
	savePromptOverride: vi.fn(),
	deletePromptOverride: vi.fn(),
	setPromptEnabled: vi.fn()
}));

const TEACHING = 'teacher/20-teaching.md';
const VOICE = 'shared/10-voice.md';
let overrides: Record<string, string | null>;
let enabled: Record<string, boolean>;

function segment(path: string, shared = false): api.PromptSegment {
	const override_text = overrides[path] ?? null;
	return {
		path,
		source_text: `# Default ${path}`,
		override_text,
		enabled: enabled[path] === true && override_text !== null,
		shared
	};
}

beforeEach(() => {
	vi.resetAllMocks();
	overrides = {};
	enabled = {};
	vi.mocked(api.getPrompts).mockImplementation(async () => ({
		teacher: [segment(TEACHING), segment(VOICE, true)],
		prober: [segment('prober/10-probe-doctrine.md'), segment(VOICE, true)],
		practice: [segment('practice/00-base.md')]
	}));
	vi.mocked(api.savePromptOverride).mockImplementation(async (path, text) => {
		overrides[path] = text;
	});
	vi.mocked(api.setPromptEnabled).mockImplementation(async (path, on) => {
		enabled[path] = on;
	});
	vi.mocked(api.deletePromptOverride).mockImplementation(async (path) => {
		delete overrides[path];
		delete enabled[path];
	});
});

test('prompts_group_teacher_prober_practice_then_shared_with_their_users', async () => {
	const screen = await render(SettingsPrompts);
	await expect.element(screen.getByTestId('prompt-section-teacher')).toBeVisible();
	await expect.element(screen.getByTestId('prompt-section-prober')).toBeVisible();
	await expect.element(screen.getByTestId('prompt-section-practice')).toBeVisible();
	const shared = screen.getByTestId('prompt-section-shared');
	await expect.element(shared.getByText('Used by Teacher and Prober')).toBeVisible();
	const row = screen.getByTestId(`prompt-row-${TEACHING}`);
	await expect.element(row.getByText('Default', { exact: true })).toBeVisible();
	await expect
		.element(screen.getByRole('switch', { name: 'Use your override for Teaching' }))
		.toBeDisabled();
});

test('view_default_shows_the_shipped_text_read_only_and_renders_a_preview', async () => {
	const screen = await render(SettingsPrompts);
	await screen
		.getByTestId(`prompt-row-${TEACHING}`)
		.getByRole('button', { name: 'View default' })
		.click();
	const dialog = page.getByRole('dialog', { name: 'View default' });
	await expect
		.element(
			dialog
				.getByLabelText('Rendered Markdown')
				.getByRole('heading', { name: `Default ${TEACHING}` })
		)
		.toBeVisible();
	await dialog.getByRole('button', { name: 'Markdown' }).click();
	const field = dialog.getByLabelText('Default Markdown');
	await expect.element(field).toHaveValue(`# Default ${TEACHING}`);
	await expect.element(field).toHaveAttribute('readonly');
	await expect
		.element(dialog.getByRole('button', { name: 'Save and activate' }))
		.not.toBeInTheDocument();
	await dialog.getByRole('button', { name: 'Close' }).click();
	await expect.element(dialog).not.toBeInTheDocument();
});

test('save_and_activate_writes_the_override_then_switches_it_on', async () => {
	const screen = await render(SettingsPrompts);
	await screen.getByRole('button', { name: '+ Add override' }).first().click();
	const dialog = page.getByRole('dialog', { name: 'Add override' });
	const field = dialog.getByLabelText('Override Markdown');
	await expect.element(field).toHaveValue(`# Default ${TEACHING}`);
	await expect.element(dialog.getByRole('button', { name: 'Save and activate' })).toBeDisabled();
	await field.fill('# Mine');
	await dialog.getByRole('button', { name: 'Save and activate' }).click();
	await expect.element(dialog).not.toBeInTheDocument();
	expect(api.savePromptOverride).toHaveBeenCalledWith(TEACHING, '# Mine');
	expect(api.setPromptEnabled).toHaveBeenCalledWith(TEACHING, true);
	const row = screen.getByTestId(`prompt-row-${TEACHING}`);
	await expect.element(row.getByText('Your version')).toBeVisible();
	await expect.element(row.getByRole('button', { name: 'Edit override' })).toBeVisible();
	await expect
		.element(screen.getByRole('switch', { name: 'Use your override for Teaching' }))
		.toBeChecked();
});

test('a_failed_save_keeps_the_dialog_and_the_edits', async () => {
	vi.mocked(api.savePromptOverride).mockRejectedValue(new Error('disk'));
	const screen = await render(SettingsPrompts);
	await screen.getByRole('button', { name: '+ Add override' }).first().click();
	const dialog = page.getByRole('dialog', { name: 'Add override' });
	await dialog.getByLabelText('Override Markdown').fill('# Mine');
	await dialog.getByRole('button', { name: 'Save and activate' }).click();
	await expect
		.element(dialog.getByRole('alert'))
		.toHaveTextContent("Couldn't save the override. Your edits are still here.");
	await expect.element(dialog.getByLabelText('Override Markdown')).toHaveValue('# Mine');
	expect(api.setPromptEnabled).not.toHaveBeenCalled();
	expect(overrides[TEACHING]).toBeUndefined();
});

test('a_failed_activation_retries_without_rewriting_the_file', async () => {
	vi.mocked(api.setPromptEnabled).mockRejectedValueOnce(new Error('settings'));
	const screen = await render(SettingsPrompts);
	await screen.getByRole('button', { name: '+ Add override' }).first().click();
	const dialog = page.getByRole('dialog');
	await dialog.getByLabelText('Override Markdown').fill('# Mine');
	await dialog.getByRole('button', { name: 'Save and activate' }).click();
	await expect
		.element(dialog.getByRole('alert'))
		.toHaveTextContent("Override saved, but it couldn't be put in use. Retry activation below.");
	await expect.element(dialog).toHaveAccessibleName('Edit override');
	await dialog.getByRole('button', { name: 'Retry activation' }).click();
	await expect.element(dialog).not.toBeInTheDocument();
	expect(api.savePromptOverride).toHaveBeenCalledTimes(1);
	expect(api.setPromptEnabled).toHaveBeenCalledTimes(2);
	expect(enabled[TEACHING]).toBe(true);
});

test('closing_with_unsaved_edits_asks_before_discarding', async () => {
	overrides[TEACHING] = '# Saved';
	const screen = await render(SettingsPrompts);
	await screen.getByRole('button', { name: 'Edit override' }).first().click();
	const dialog = page.getByRole('dialog', { name: 'Edit override' });
	const field = dialog.getByLabelText('Override Markdown');
	await field.fill('# Changed');
	await dialog.getByRole('button', { name: 'Close' }).click();
	await expect.element(dialog.getByText('Discard unsaved changes?')).toBeVisible();
	await dialog.getByRole('button', { name: 'Keep editing' }).click();
	await expect.element(field).toHaveValue('# Changed');
	await dialog.getByRole('button', { name: 'Close' }).click();
	await dialog.getByRole('button', { name: 'Discard changes' }).click();
	await expect.element(dialog).not.toBeInTheDocument();
	expect(api.savePromptOverride).not.toHaveBeenCalled();
	expect(overrides[TEACHING]).toBe('# Saved');
});

test('delete_override_removes_it_and_reports_a_failure', async () => {
	overrides[TEACHING] = '# Saved';
	enabled[TEACHING] = true;
	const screen = await render(SettingsPrompts);
	await screen.getByRole('button', { name: 'Edit override' }).first().click();
	const dialog = page.getByRole('dialog', { name: 'Edit override' });
	vi.mocked(api.deletePromptOverride).mockRejectedValueOnce(new Error('disk'));
	await dialog.getByRole('button', { name: 'Delete override' }).click();
	await expect
		.element(dialog.getByRole('alert'))
		.toHaveTextContent("Couldn't delete the override.");
	await dialog.getByRole('button', { name: 'Delete override' }).click();
	await expect.element(dialog).not.toBeInTheDocument();
	const row = screen.getByTestId(`prompt-row-${TEACHING}`);
	await expect.element(row.getByRole('button', { name: '+ Add override' })).toBeVisible();
	await expect.element(row.getByText('Default', { exact: true })).toBeVisible();
});

test('the_switch_uses_a_saved_override_or_the_default_and_reports_failures', async () => {
	overrides[TEACHING] = '# Saved';
	const screen = await render(SettingsPrompts);
	const toggle = screen.getByRole('switch', { name: 'Use your override for Teaching' });
	await toggle.click();
	await expect.element(toggle).toBeChecked();
	expect(api.setPromptEnabled).toHaveBeenLastCalledWith(TEACHING, true);
	vi.mocked(api.setPromptEnabled).mockRejectedValueOnce(new Error('settings'));
	await toggle.click();
	await expect
		.element(screen.getByTestId(`prompt-row-${TEACHING}`).getByRole('alert'))
		.toHaveTextContent("Couldn't switch prompt versions.");
	await expect.element(toggle).toBeChecked();
	await toggle.click();
	await expect.element(toggle).not.toBeChecked();
	expect(enabled[TEACHING]).toBe(false);
});

test('a_failed_load_offers_retry', async () => {
	vi.mocked(api.getPrompts).mockRejectedValueOnce(new Error('down'));
	const screen = await render(SettingsPrompts);
	await expect
		.element(screen.getByRole('alert'))
		.toHaveTextContent("Couldn't load prompt segments.");
	await screen.getByRole('button', { name: 'Retry' }).click();
	await expect.element(screen.getByTestId('prompt-section-teacher')).toBeVisible();
});
