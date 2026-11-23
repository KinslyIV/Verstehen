import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { test, expect } from '../fixtures';

test.use({ script: 'verify/scripts/health.json' });

const TEACHING = 'teacher/20-teaching.md';

test('settings-prompts', async ({ page, request, dataDirectory }) => {
	const segments = async () => {
		const view = await (await request.get('/api/prompts')).json();
		return view.teacher.find((segment: { path: string }) => segment.path === TEACHING);
	};
	await page.goto('/settings');
	await page.getByRole('button', { name: 'Prompts', exact: true }).click();
	await expect(page).toHaveURL(/section=prompts/);
	for (const section of ['teacher', 'prober', 'practice', 'shared'])
		await expect(page.getByTestId(`prompt-section-${section}`)).toBeVisible();
	const row = page.getByTestId(`prompt-row-${TEACHING}`);
	const toggle = page.getByRole('switch', { name: 'Use your override for Teaching' });
	await expect(toggle).toBeDisabled();
	await expect(row.getByText('Default', { exact: true })).toBeVisible();

	await row.getByRole('button', { name: 'View default' }).click();
	const viewer = page.getByRole('dialog', { name: 'View default' });
	await expect(viewer.getByLabel('Rendered Markdown')).not.toBeEmpty();
	await page.screenshot({ path: test.info().outputPath('prompt-view-default.png') });
	await viewer.getByRole('button', { name: 'Close' }).click();
	await expect(viewer).toBeHidden();

	await row.getByRole('button', { name: '+ Add override' }).click();
	const editor = page.getByRole('dialog', { name: 'Add override' });
	await editor.getByLabel('Override Markdown').fill('# Verify override\n\nTeach with care.');
	await editor.getByRole('button', { name: 'Preview' }).click();
	await expect(editor.getByRole('heading', { name: 'Verify override' })).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('prompt-edit-preview.png') });
	await editor.getByRole('button', { name: 'Save and activate' }).click();
	await expect(editor).toBeHidden();
	await expect(row.getByText('Your version')).toBeVisible();
	await expect(toggle).toBeChecked();
	expect(await segments()).toMatchObject({ enabled: true });
	expect(await readFile(resolve(dataDirectory, 'prompts', TEACHING), 'utf8')).toBe(
		'# Verify override\n\nTeach with care.'
	);

	await toggle.click();
	await expect(row.getByText('Default', { exact: true })).toBeVisible();
	expect(await segments()).toMatchObject({ enabled: false });
	expect(await segments()).toMatchObject({
		override_text: '# Verify override\n\nTeach with care.'
	});
	const reenable = page.waitForResponse(
		(response) =>
			response.request().method() === 'PUT' &&
			response.url().includes(`/api/prompts/${TEACHING}/enabled`) &&
			response.status() === 200
	);
	await toggle.click();
	await reenable;
	await expect(row.getByText('Your version', { exact: true })).toBeVisible();
	await expect(toggle).toBeChecked();
	await expect(toggle).toBeEnabled();
	expect(await segments()).toMatchObject({ enabled: true });

	await page.reload();
	await expect(toggle).toBeChecked();
	await row.getByRole('button', { name: 'Edit override' }).click();
	const again = page.getByRole('dialog', { name: 'Edit override' });
	await again.getByLabel('Override Markdown').fill('# Unsaved draft');
	await again.getByRole('button', { name: 'Close' }).click();
	await expect(again.getByText('Discard unsaved changes?')).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('prompt-discard-confirm.png') });
	await again.getByRole('button', { name: 'Keep editing' }).click();
	await expect(again.getByLabel('Override Markdown')).toHaveValue('# Unsaved draft');
	await again.getByRole('button', { name: 'Close' }).click();
	await again.getByRole('button', { name: 'Discard changes' }).click();
	await expect(again).toBeHidden();
	expect(await segments()).toMatchObject({
		override_text: '# Verify override\n\nTeach with care.'
	});

	await row.getByRole('button', { name: 'Edit override' }).click();
	const removing = page.getByRole('dialog', { name: 'Edit override' });
	await removing.getByRole('button', { name: 'Delete override' }).click();
	await expect(removing).toBeHidden();
	await expect(row.getByRole('button', { name: '+ Add override' })).toBeVisible();
	await expect(toggle).toBeDisabled();
	expect(await segments()).toMatchObject({ override_text: null, enabled: false });
	await page.screenshot({ path: test.info().outputPath('prompts-after-delete.png') });
});
