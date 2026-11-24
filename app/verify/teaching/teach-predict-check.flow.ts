import { test, expect } from '../fixtures';
import { startLesson, selectOption } from '../questions';
import { planPanel, sendLessonMessage, waitForPlan } from '../teaching';

test.use({ script: 'verify/scripts/teach-predict-check.json' });

test('teach-predict-check', async ({ page }) => {
	await startLesson(page);
	await waitForPlan(page);
	const panel = planPanel(page);
	await expect(panel.getByTestId('plan-node-slope')).toHaveAttribute('data-status', 'upcoming');
	await page.getByRole('button', { name: 'Toggle right panel' }).click();
	await expect(panel).toBeHidden();
	await page.getByTestId('plan-block').click();
	await waitForPlan(page);

	await sendLessonMessage(page, 'Let’s start.');
	const dock = page.getByTestId('question-dock');
	await expect(dock.getByText('Prediction', { exact: true })).toBeVisible();
	await expect(page.getByTestId('teach-check-reveal')).toBeHidden();
	await expect(page.getByTestId('phase-chip')).toHaveText('Teaching');
	await expect(page.getByTestId('phase-divider-teach')).toHaveCount(1);
	await expect(panel.getByTestId('plan-node-slope')).toHaveAttribute('data-status', 'current');
	await expect(panel.getByTestId('plan-current-glow')).toBeVisible();

	const view = panel.getByTestId('plan-view');
	const initial = Number(await view.getAttribute('data-zoom'));
	await panel.getByRole('button', { name: 'Zoom in' }).click();
	await expect
		.poll(async () => Number(await view.getAttribute('data-zoom')))
		.toBeGreaterThan(initial);
	const viewport = panel.getByRole('region', { name: /Plan viewport/ });
	const box = (await viewport.boundingBox())!;
	const beforeDrag = await view.getAttribute('style');
	await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
	await page.mouse.down();
	await page.mouse.move(box.x + box.width / 2 + 35, box.y + box.height / 2 + 15);
	await page.mouse.up();
	await expect(view).not.toHaveAttribute('style', beforeDrag!);
	await panel.getByRole('button', { name: 'Fit plan to screen' }).click();
	await expect.poll(async () => Number(await view.getAttribute('data-zoom'))).toBe(initial);
	await panel.getByRole('button', { name: 'Zoom in' }).click();
	await panel.getByRole('button', { name: 'Zoom out' }).click();
	await expect.poll(async () => Number(await view.getAttribute('data-zoom'))).toBeCloseTo(initial);

	await selectOption(page, 'The steeper line');
	await page.getByRole('button', { name: 'Submit answer' }).click();
	const reveal = page.getByTestId('teach-check-reveal');
	await expect(reveal).toBeVisible();
	await expect(dock).toBeHidden();
	await expect(panel.getByTestId('plan-node-slope')).toHaveAttribute('data-status', 'visited');
	await expect(panel.getByTestId('plan-node-secant')).toHaveAttribute('data-status', 'current');
	await page.reload();
	await expect(reveal).toBeVisible();
	await expect(dock).toBeHidden();
	const reading = page.getByRole('textbox', { name: 'Thinking while reading' });
	await reading.fill('Two points give me an average.');
	await reading.press('Enter');
	await expect(dock.getByText('Check', { exact: true })).toBeVisible();
	await expect(page.getByRole('textbox', { name: 'Your thinking' })).toHaveCSS(
		'min-height',
		'72px'
	);
	await selectOption(page, 'Average rate of change');
	await page.getByRole('button', { name: 'Submit answer' }).click();
	await expect(page.getByTestId('reading-thinking-block')).toContainText(
		'Two points give me an average.'
	);
	await expect(page.getByTestId('phase-divider-teach')).toHaveCount(1);
	await expect(page.getByText('Exactly. That average rate is the secant slope.')).toBeVisible();
	await page.getByTestId('plan-block').click();
	await expect(panel.getByTestId('plan-node-secant')).toHaveAttribute('data-status', 'current');
});
