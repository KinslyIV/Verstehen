import { test, expect } from '../fixtures';
import { startLesson } from '../questions';

test.use({
	script: 'verify/scripts/question-probe-answer.json',
	viewport: { width: 360, height: 780 },
	hasTouch: true,
	isMobile: true
});

test('mobile-question-dock', async ({ page }) => {
	await startLesson(page);
	const dock = page.getByTestId('question-dock');
	await expect(dock).toContainText('What is the slope of a horizontal line?');
	const box = (await dock.boundingBox())!;
	expect(box.x).toBeGreaterThanOrEqual(0);
	expect(box.x + box.width).toBeLessThanOrEqual(360);
	expect(box.y + box.height).toBeLessThanOrEqual(780);
	await page.screenshot({ path: test.info().outputPath('dock.png'), animations: 'disabled' });

	await page.getByRole('radio', { name: 'Zero', exact: true }).tap();
	await expect(page.getByRole('radio', { name: 'Zero', exact: true })).toHaveAttribute(
		'aria-checked',
		'true'
	);
	await dock.getByTestId('confidence-value').scrollIntoViewIfNeeded();
	await dock.getByRole('button', { name: 'Submit answer' }).tap();
	const card = page.getByTestId('answered-card');
	await expect(card.getByText('correct', { exact: true })).toBeVisible();
	await expect(page.getByText(/This is the derivative of a constant/)).toBeInViewport();
	await page.screenshot({ path: test.info().outputPath('answered.png'), animations: 'disabled' });
});
