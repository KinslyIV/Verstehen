import { test, expect } from '../fixtures';
test.use({ script: 'verify/scripts/slow.json' });
test('session-reload-mid-turn', async ({ page }) => {
	await page.goto('/');
	await page.getByRole('textbox', { name: 'What do you want to learn?' }).fill('Derivatives');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);
	await expect(page.getByText('A derivative describes', { exact: false })).toBeVisible();
	await page.reload();
	await expect(
		page.getByText(
			'A derivative describes how quickly a quantity changes. What do you already know about slope?',
			{ exact: true }
		)
	).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	await expect(page.locator('[data-slot="message"]')).toHaveCount(2);
});
