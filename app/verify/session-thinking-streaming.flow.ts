import { test, expect } from './fixtures';
test.use({ script: 'verify/scripts/thinking.json' });
for (const theme of ['dark', 'light'])
	test(`session-thinking-streaming-${theme}`, async ({ page }) => {
		await page.addInitScript((theme) => localStorage.setItem('mode-watcher-mode', theme), theme);
		await page.goto('/');
		await page.getByRole('textbox').fill('Understanding derivatives');
		await page.getByRole('button', { name: 'Send', exact: true }).click();
		const thinking = page.getByRole('button', { name: 'Thinking...', exact: true });
		await expect(thinking).toHaveAttribute('aria-expanded', 'false');
		await thinking.click();
		await expect(
			page.getByText('Let me connect this idea to what you already know.')
		).toBeVisible();
		await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible();
	});
