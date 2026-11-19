import { test, expect } from './fixtures';
test.use({ script: 'verify/scripts/markdown.json' });
for (const theme of ['dark', 'light'])
	test(`markdown-rendering-${theme}`, async ({ page }) => {
		await page.addInitScript((theme) => localStorage.setItem('mode-watcher-mode', theme), theme);
		await page.goto('/');
		await page.getByRole('textbox').fill('Show **plain learner text**');
		await page.getByRole('button', { name: 'Send', exact: true }).click();
		await expect(page).toHaveURL(/\/session\/[^/]+$/);
		await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
		await expect(page.locator('.katex').first()).toBeVisible();
		await expect(page.locator('pre code')).toContainText('const rate');
		await expect(page.locator('[data-testid=md-mermaid] svg')).toBeVisible();
		await page.getByRole('heading', { name: 'Understanding change' }).scrollIntoViewIfNeeded();
	});
