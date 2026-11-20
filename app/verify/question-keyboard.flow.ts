import { test, expect } from './fixtures';
import { startLesson } from './questions';

test.use({ script: 'verify/scripts/question-probe-answer.json' });

test('question-keyboard', async ({ page }) => {
	await startLesson(page);
	const dock = page.getByTestId('question-dock');
	const firstRow = dock.getByRole('radio').first();
	await expect(firstRow).toBeVisible();
	await expect(dock.getByRole('button', { name: 'Stop' })).toBeHidden();
	await page.keyboard.press('ArrowDown');
	await page.keyboard.press('ArrowUp');
	await page.keyboard.press('ArrowUp');
	await page.keyboard.press('Space');
	await expect(firstRow).toHaveAttribute('aria-checked', 'true');
	await page.keyboard.press('Tab');
	await expect(firstRow).toBeFocused();
	await page.keyboard.press('Tab');
	await expect(dock.getByRole('textbox', { name: 'Your thinking' })).toBeFocused();
	await page.keyboard.press('Tab');
	await expect(firstRow).toBeFocused();
	await page.keyboard.press('ArrowLeft');
	await expect(dock.getByTestId('confidence-value')).toHaveText('30%');
	await page.keyboard.press('ArrowRight');
	await page.keyboard.press('ArrowRight');
	await page.keyboard.press('Enter');
	await expect(page.getByTestId('answered-card').getByTestId('answered-confidence')).toHaveText(
		'70%'
	);
});
