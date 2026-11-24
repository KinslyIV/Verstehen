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
	const geometry = () =>
		viewport.evaluate((element) => ({
			client: element.clientHeight,
			scroll: element.scrollHeight
		}));
	const open = await geometry();
	await viewport.hover({ position: { x: 200, y: 40 } });
	await page.mouse.wheel(0, -550);
	await expect(bar).toBeVisible();
	expect(await geometry()).toEqual(open);
	await expect(dock).toBeHidden();
	await expect(dock).toHaveCount(1);
	await viewport.evaluate((element) => {
		element.scrollTop = element.scrollHeight;
	});
	await expect(dock).toBeVisible();
	expect(await geometry()).toEqual(open);
	const lastLine = await viewport.evaluate((element) => {
		const rows = element.querySelectorAll('[data-slot="message-scroller-item"]');
		return rows[rows.length - 1].getBoundingClientRect().bottom;
	});
	expect(lastLine).toBeLessThanOrEqual((await dock.boundingBox())!.y);
	await viewport.evaluate((element) => {
		element.scrollTop = 0;
	});
	await expect(bar).toBeVisible();
	await bar.click();
	await expect(dock.getByRole('textbox', { name: 'Your thinking' })).toHaveValue(
		'My draft while I read.'
	);
	await expect(dock.getByRole('radio', { name: 'Zero' })).toHaveAttribute('aria-checked', 'true');
	const before = await viewport.evaluate((element) => element.scrollTop);
	await dock.getByText('Your thinking').first().hover();
	await page.mouse.wheel(0, -30);
	await expect.poll(() => viewport.evaluate((element) => element.scrollTop)).toBeLessThan(before);
});
