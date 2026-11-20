import { test, expect } from './fixtures';
import { startLesson } from './questions';

test.use({ script: 'verify/scripts/slow.json' });

test('turn-abort-esc', async ({ page }) => {
	await startLesson(page);
	await expect(page.getByText('A derivative describes', { exact: false })).toBeVisible();
	await page.keyboard.press('Escape');
	const dialog = page.getByRole('dialog', { name: 'Abort this turn?' });
	await expect(dialog).toContainText('The partial answer stays in the transcript.');
	await dialog.getByRole('button', { name: 'Abort', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	const text = await page.locator('.markdown').innerText();
	await page.reload();
	await expect(page.locator('.markdown')).toHaveText(text);
});
