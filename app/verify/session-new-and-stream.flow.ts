import { test, expect } from './fixtures';
test.use({ script: 'verify/scripts/session.json' });
for (const theme of ['dark', 'light'])
	test(`session-new-and-stream-${theme}`, async ({ page }) => {
		await page.addInitScript((theme) => localStorage.setItem('mode-watcher-mode', theme), theme);
		await page.goto('/');
		await page.getByRole('textbox').fill('Understanding derivatives');
		await page.getByRole('button', { name: 'Send', exact: true }).click();
		await expect(page).toHaveURL(/\/session\/[^/]+$/);
		const thinking = page.getByRole('button', { name: 'Thinking...', exact: true });
		await expect(thinking).toHaveAttribute('aria-expanded', 'false');
		await thinking.click();
		await expect(thinking).toHaveAttribute('aria-expanded', 'true');
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
		await page.waitForTimeout(1200);
		await expect(page.getByRole('button', { name: "AGENT'S THINKING" })).toHaveAttribute(
			'aria-expanded',
			'true'
		);
		await expect(page.getByRole('link', { name: /Understanding derivatives/ })).toContainText(
			'just now'
		);
	});
