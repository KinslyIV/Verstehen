import { test, expect } from '../fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('settings', async ({ page, request }) => {
	const saved = async () => await (await request.get('/api/settings')).json();
	await page.goto('/settings');
	await page.getByRole('button', { name: 'Light', exact: true }).click();
	await expect(page.locator('html')).not.toHaveClass(/dark/);
	await expect(page.getByRole('heading', { name: 'Appearance', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Light', exact: true })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	await page.screenshot({
		path: test.info().outputPath('settings-light.png'),
		animations: 'disabled'
	});

	await page.getByRole('button', { name: 'Models', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Choose Main model' })).toContainText(
		'Scripted teacher'
	);
	await expect(page.getByRole('button', { name: 'Choose Cheap model' })).toContainText(
		'Scripted title'
	);
	await expect(page.getByRole('button', { name: 'Choose Vision model' })).toContainText(
		'Scripted teacher'
	);

	await page.getByRole('button', { name: 'Lesson', exact: true }).click();
	const limit = page.getByRole('spinbutton', { name: 'Compaction limit' });
	await limit.fill('64000');
	await limit.press('Enter');
	await expect.poll(async () => (await saved()).compaction_limit).toBe(64_000);
	const row = page.getByTestId('file-access-row');
	const restrict = row.getByRole('switch', { name: 'Restrict to listed folders' });
	await restrict.click();
	const folder = row.getByRole('textbox', { name: 'Allowed folder path' });
	await folder.fill('~/Notes');
	await folder.press('Enter');
	await expect(row.getByText('Only listed folders and subfolders.')).toBeVisible();
	await page.reload();
	await page.getByRole('button', { name: 'Lesson', exact: true }).click();
	await expect(limit).toHaveValue('64000');
	await expect(restrict).toHaveAttribute('aria-checked', 'true');
	await expect(row.getByText('~/Notes', { exact: true })).toBeVisible();
	await limit.fill('');
	await limit.press('Enter');
	await expect.poll(async () => (await saved()).compaction_limit).toBeNull();

	await page.getByRole('button', { name: 'Graph', exact: true }).click();
	const extraction = page.getByRole('switch', { name: 'extraction enabled' });
	const rendering = page.getByRole('switch', { name: 'graph rendering enabled' });
	const graphTools = page.getByRole('switch', { name: 'graph tools' });
	await expect(extraction).toBeChecked();
	await expect(rendering).toBeChecked();
	await expect(graphTools).toBeChecked();
	await graphTools.click();
	await expect.poll(async () => (await saved()).agent?.graph_tools).toBe(false);
	await rendering.click();
	await expect.poll(async () => (await saved()).graph?.rendering).toBe(false);
	await extraction.click();
	await expect.poll(async () => (await saved()).graph?.enabled).toBe(false);

	await page.getByRole('button', { name: 'Tools', exact: true }).click();
	const concurrency = page.getByRole('spinbutton', { name: 'Concurrent worker requests' });
	await concurrency.fill('4');
	await concurrency.press('Enter');
	await expect.poll(async () => (await saved()).worker_request_concurrency).toBe(4);
});
