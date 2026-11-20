import { test, expect } from './fixtures';
import { startLesson } from './questions';
import { planPanel, sendLessonMessage, waitForPlan } from './teaching';

test.use({ script: 'verify/scripts/teach-predict-check.json' });

test('plan-diagram', async ({ page }) => {
	await startLesson(page);
	await waitForPlan(page);
	const panel = planPanel(page);
	await expect(panel.getByTestId('plan-node-slope')).toHaveAttribute('data-status', 'upcoming');
	await page.getByRole('button', { name: 'Toggle right panel' }).click();
	await expect(panel).toBeHidden();
	await page.getByTestId('plan-block').click();
	await waitForPlan(page);
	await sendLessonMessage(page, 'Let’s start.');
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
});
