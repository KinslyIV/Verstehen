import { expect, test } from './fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('settings-compaction-limit', async ({ page, request }) => {
	await page.goto('/settings');
	await page.getByRole('button', { name: 'Lesson', exact: true }).click();
	const field = page.getByRole('spinbutton', { name: 'Compaction limit' });
	await expect(field).toHaveAccessibleDescription(
		"Summarize older history when the lesson's context passes this many tokens"
	);
	await expect(field).toHaveAttribute('placeholder', '150000');
	const saved = async () => (await (await request.get('/api/settings')).json()).compaction_limit;
	await field.fill('200000');
	await field.press('Enter');
	await expect.poll(saved).toBe(200_000);
	await field.fill('1000');
	await page.getByText('Compaction limit', { exact: true }).click();
	await expect.poll(saved).toBe(32_000);
	await expect(field).toHaveValue('32000');
	await field.fill('-5');
	await page.getByText('Compaction limit', { exact: true }).click();
	await expect(field).toHaveValue('32000');
	expect(await saved()).toBe(32_000);
	await page.reload();
	await page.getByRole('button', { name: 'Lesson', exact: true }).click();
	await expect(field).toHaveValue('32000');
	await field.fill('');
	await field.press('Enter');
	await expect.poll(saved).toBeNull();
	await expect(field).toHaveValue('');
	await page.screenshot({ path: test.info().outputPath('default.png'), animations: 'disabled' });
});
