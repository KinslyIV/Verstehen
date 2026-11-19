import { test, expect } from './fixtures';
test.use({ script: 'verify/scripts/slow.json' });
test('session-stop', async ({ page }) => {
	await page.goto('/');
	await page.getByRole('textbox').fill('Derivatives');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);
	await expect(page.getByText('A derivative describes', { exact: false })).toBeVisible();
	await page.getByRole('button', { name: 'Stop', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	const text = await page.locator('.markdown').innerText();
	await page.reload();
	await expect(page.locator('.markdown')).toHaveText(text);
});
