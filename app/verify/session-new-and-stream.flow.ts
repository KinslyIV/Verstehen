import { test, expect } from './fixtures';
test.use({ script: 'verify/scripts/session.json' });
for (const theme of ['dark', 'light'])
	test(`session-new-and-stream-${theme}`, async ({ page }) => {
		await page.addInitScript((theme) => localStorage.setItem('mode-watcher-mode', theme), theme);
		await page.goto('/');
		await page.getByRole('textbox').fill('Understanding derivatives');
		await page.getByRole('button', { name: 'Send', exact: true }).click();
		await expect(page).toHaveURL(/\/session\/[^/]+$/);
		await expect(page).toHaveURL(/\/session\/[^/]+$/);
		await expect(page.getByText('Thinking...', { exact: true })).toBeVisible();
		await expect(page.getByText('A derivative describes', { exact: false })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
		await expect(page.getByRole('button', { name: "AGENT'S THINKING" })).toHaveAttribute(
			'aria-expanded',
			'false'
		);
		await page.getByRole('button', { name: "AGENT'S THINKING" }).click();
		await expect(
			page.getByText('Let me connect this idea to what you already know.')
		).toBeVisible();
		await expect(page.getByRole('link', { name: /Understanding derivatives/ })).toContainText(
			'just now'
		);
	});
