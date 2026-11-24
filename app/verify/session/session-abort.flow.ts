import { test, expect } from '../fixtures';

test.use({ script: 'verify/scripts/session-abort.json' });

test('session-abort', async ({ page }) => {
	await page.goto('/');
	await page.getByRole('textbox', { name: 'What do you want to learn?' }).fill('Derivatives');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);
	await expect(page.getByText('A derivative describes', { exact: false })).toBeVisible();
	await page.getByRole('button', { name: 'Stop', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	const firstText = await page.locator('.markdown').first().innerText();
	expect(firstText).toContain('A derivative describes');
	expect(firstText).not.toContain('about slope?');
	await page.reload();
	await expect(page.locator('.markdown').first()).toHaveText(firstText);

	await page.getByRole('textbox', { name: 'What do you want to learn?' }).fill('Integrals');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByText('An integral accumulates', { exact: false })).toBeVisible();
	await page.keyboard.press('Escape');
	const dialog = page.getByRole('dialog', { name: 'Abort this turn?' });
	await expect(dialog).toContainText('The partial answer stays in the transcript.');
	await dialog.getByRole('button', { name: 'Abort', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	const secondText = await page.locator('.markdown').nth(1).innerText();
	expect(secondText).toContain('An integral accumulates');
	expect(secondText).not.toContain('total change.');
	await page.reload();
	await expect(page.locator('.markdown').nth(1)).toHaveText(secondText);
});
