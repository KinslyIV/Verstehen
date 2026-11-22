import { test, expect } from '../fixtures';
import { selectOption, startLesson } from '../questions';

test.use({ script: 'verify/scripts/question-collapse.json' });

test('question-collapse', async ({ page }) => {
	await startLesson(page);
	const dock = page.getByTestId('question-dock');
	const bar = page.getByRole('button', { name: /Probe.*What is the slope.*Answer/ });
	if (await bar.isVisible()) await bar.click();
	await selectOption(page, 'Zero');
	await dock.getByRole('textbox', { name: 'Your thinking' }).fill('My draft while I read.');
	const viewport = page.getByLabel('Conversation');
	await viewport.evaluate((element) => {
		element.scrollTop = element.scrollHeight;
	});
	await expect(dock).toBeVisible();
	await viewport.hover();
	await page.mouse.wheel(0, -550);
	await expect(bar).toBeVisible();
	await expect(dock).toBeHidden();
	await expect(dock).toHaveCount(1);
	await bar.click();
	await expect(dock.getByRole('textbox', { name: 'Your thinking' })).toHaveValue(
		'My draft while I read.'
	);
	await expect(dock.getByRole('radio', { name: 'Zero' })).toHaveAttribute('aria-checked', 'true');
});
