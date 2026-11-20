import { test, expect } from './fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('settings-file-access', async ({ page }) => {
	await page.goto('/settings');
	await page.getByRole('button', { name: 'Lesson', exact: true }).click();
	const row = page.getByTestId('file-access-row');
	const setting = row.getByRole('switch', { name: 'Restrict to listed folders' });
	await expect(setting).toHaveAttribute('aria-checked', 'false');
	await expect(
		row.getByText('Broad local source access, except protected locations')
	).toBeVisible();
	await setting.click();
	await expect(
		row.getByText('Restricted: no folders allowed. Add a folder to enable access.')
	).toBeVisible();
	const folder = row.getByRole('textbox', { name: 'Allowed folder path' });
	await folder.fill('relative/path');
	await row.getByRole('button', { name: 'Add folder' }).click();
	await expect(row.getByRole('alert')).toHaveText('Enter an absolute path or ~/folder.');
	await folder.fill(' ~/Notes ');
	await folder.press('Enter');
	await expect(row.getByText('Only listed folders and subfolders.')).toBeVisible();
	await folder.fill('/tmp/lesson-notes');
	await row.getByRole('button', { name: 'Add folder' }).click();
	await expect(row.getByRole('button', { name: 'Remove /tmp/lesson-notes' })).toBeVisible();
	await page.reload();
	await page.getByRole('button', { name: 'Lesson', exact: true }).click();
	await expect(setting).toHaveAttribute('aria-checked', 'true');
	await row.getByRole('button', { name: 'Remove /tmp/lesson-notes' }).click();
	await expect(row.getByRole('button', { name: 'Remove /tmp/lesson-notes' })).toHaveCount(0);
	await expect(row.getByText('~/Notes', { exact: true })).toBeVisible();
});
