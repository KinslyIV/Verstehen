import { test, expect } from '../fixtures';
import { planPanel } from '../teaching';
import { sideThread, startTaughtLesson } from '../side-chat';

test.use({
	script: 'verify/scripts/side-chat-delivery.json',
	viewport: { width: 360, height: 780 },
	hasTouch: true,
	isMobile: true
});

test('mobile-right-panel', async ({ page }) => {
	await startTaughtLesson(page, 'A derivative describes how quickly');
	const screen = page.getByTestId('phone-tab-screen');
	const tabs = page.getByRole('group', { name: 'Right panel' });
	await expect(screen).toHaveCount(0);

	await tabs.getByRole('button', { name: 'Plan', exact: true }).tap();
	await expect(screen).toBeVisible();
	await expect(page.getByTestId('phone-heading')).toHaveText('Plan');
	await page.screenshot({ path: test.info().outputPath('phone-plan.png'), animations: 'disabled' });
	await page.getByTestId('phone-lesson').tap();
	await expect(screen).toHaveCount(0);

	await page.getByTestId('side-conversation-button').tap();
	await expect(screen).toBeVisible();
	await expect(sideThread(page).getByTestId('side-thread-input')).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('phone-side.png'), animations: 'disabled' });
	await page.getByTestId('phone-lesson').tap();

	await page.evaluate(() => {
		const walker = document.createTreeWalker(
			document.querySelector('[data-source-entry-id]')!,
			NodeFilter.SHOW_TEXT
		);
		let text = walker.nextNode()!;
		while (!text.textContent?.includes('derivative describes how quickly'))
			text = walker.nextNode()!;
		const start = text.textContent!.indexOf('derivative');
		const range = document.createRange();
		range.setStart(text, start);
		range.setEnd(text, start + 'derivative describes how quickly'.length);
		window.getSelection()!.removeAllRanges();
		window.getSelection()!.addRange(range);
	});
	const toolbar = page.getByTestId('selection-toolbar');
	await expect(toolbar).toBeVisible();
	await toolbar.getByRole('button', { name: 'Ask a side question about this selection' }).tap();
	await expect(screen).toBeVisible();
	await expect(page.getByTestId('phone-heading')).toHaveText('Side chat');
	await expect(sideThread(page).getByTestId('side-pending-quote')).toHaveText(
		'derivative describes how quickly'
	);
	await page.screenshot({ path: test.info().outputPath('phone-ask.png'), animations: 'disabled' });
	await page.getByTestId('phone-lesson').tap();

	await page.setViewportSize({ width: 800, height: 1280 });
	await expect(page.getByRole('link', { name: 'Teaching', exact: true })).toBeHidden();
	await page.getByRole('button', { name: 'Toggle right panel' }).click();
	await expect(planPanel(page)).toBeVisible();
	const panel = (await planPanel(page).boundingBox())!;
	const lesson = (await page
		.getByRole('textbox', { name: 'What do you want to learn?' })
		.boundingBox())!;
	expect(lesson.x + lesson.width).toBeLessThanOrEqual(panel.x + 1);
	await page.screenshot({
		path: test.info().outputPath('tablet-portrait.png'),
		animations: 'disabled'
	});
	await page.getByRole('button', { name: 'Toggle right panel' }).click();
	await expect(planPanel(page)).toHaveCount(0);

	await page.setViewportSize({ width: 1280, height: 800 });
	await expect(page.getByRole('link', { name: 'Teaching', exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Toggle right panel' }).click();
	await expect(planPanel(page)).toBeVisible();
	await page.screenshot({
		path: test.info().outputPath('tablet-landscape.png'),
		animations: 'disabled'
	});
});
