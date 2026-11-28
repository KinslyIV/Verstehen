import { test, expect } from '../fixtures';
import { startLesson } from '../questions';

test.use({ script: 'verify/scripts/thread-navigation.json' });

test('thread-navigation', async ({ page }) => {
	await startLesson(page, 'Teach me about derivatives');
	const dock = page.getByTestId('question-dock');
	const other = dock.getByRole('textbox', { name: 'Type your own answer' });
	await other.fill('A bike');
	await other.press('Enter');
	await expect(dock.getByText('Is a steeper hill a larger slope?')).toBeVisible();
	await other.fill('Yes');
	await other.press('Enter');
	await expect(page.getByText('Summary 8')).toBeVisible();
	const composer = page.getByRole('textbox', { name: 'What do you want to learn?' });
	await composer.fill('Can you go further?');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByText('Follow-up 8')).toBeVisible();
	await composer.fill('Say one more thing.');
	await page.getByRole('button', { name: 'Send', exact: true }).click();

	// A turn is pending: the scroll-to-bottom button still works.
	const viewport = page.getByLabel('Conversation');
	const toBottom = page.getByRole('button', { name: 'Scroll to bottom' });
	await viewport.hover();
	await page.mouse.wheel(0, -1500);
	await expect(toBottom).toHaveAttribute('data-active', 'true');
	await page.screenshot({
		path: test.info().outputPath('button-pending.png'),
		animations: 'disabled'
	});
	await toBottom.click();
	await expect(page.getByText('Slow closing remark', { exact: false })).toBeVisible({
		timeout: 15_000
	});

	// The rail has one tick per typed message and answered question.
	const rail = page.getByTestId('turn-minimap');
	const ticks = rail.getByTestId('turn-tick');
	await expect(ticks).toHaveCount(5);
	const railBox = (await rail.boundingBox())!;
	const content = (await page.getByText('Follow-up 8').boundingBox())!;
	expect(railBox.x + railBox.width).toBeLessThanOrEqual(content.x);
	await expect(ticks.last()).toHaveAttribute('data-active', 'true');

	// Hovering previews the exchange; clicking jumps to it.
	await ticks.nth(1).hover();
	const preview = page.getByTestId('turn-preview');
	await expect(preview).toContainText('Which example should we use?');
	await expect(preview).toContainText('A bike');
	await page.screenshot({ path: test.info().outputPath('hover.png'), animations: 'disabled' });
	await ticks.nth(1).click();
	await expect(page.getByTestId('answered-card').first()).toBeInViewport();
	await expect(ticks.nth(1)).toHaveAttribute('data-active', 'true');
	await page.screenshot({ path: test.info().outputPath('jumped.png'), animations: 'disabled' });

	// Scrolled away from the bottom the button appears, and returns to the bottom.
	await expect(toBottom).toHaveAttribute('data-active', 'true');
	await page.screenshot({ path: test.info().outputPath('button.png'), animations: 'disabled' });
	await toBottom.click();
	await expect(toBottom).toHaveAttribute('data-active', 'false');
	await expect(page.getByText('Slow closing remark', { exact: false })).toBeInViewport();
	await expect(ticks.last()).toHaveAttribute('data-active', 'true');
});

test.describe('on a phone', () => {
	test.use({ viewport: { width: 360, height: 780 }, hasTouch: true, isMobile: true });

	test('thread-navigation-phone', async ({ page }) => {
		await startLesson(page, 'Teach me about derivatives');
		await expect(page.getByTestId('question-dock')).toBeVisible();
		await expect(page.getByTestId('turn-minimap').getByTestId('turn-tick')).toHaveCount(1);
		await expect(page.getByTestId('turn-minimap')).toBeHidden();
		await page.screenshot({ path: test.info().outputPath('phone.png'), animations: 'disabled' });
	});
});
