import { test, expect } from './fixtures';
import { sideThread, startTaughtLesson } from './side-chat';

test.use({ script: 'verify/scripts/side-chat-selection.json' });

test('side-chat-selection', async ({ page }) => {
	await startTaughtLesson(page, 'A derivative describes how quickly');
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
	await toolbar.getByRole('button', { name: 'Ask a side question about this selection' }).click();
	await expect(toolbar).toHaveCount(0);
	await expect(page.getByRole('tab', { name: 'Side chat' })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	const quote = sideThread(page).getByTestId('side-pending-quote');
	await expect(quote).toHaveText('derivative describes how quickly');
	const input = sideThread(page).getByTestId('side-thread-input');
	await expect(input).toHaveAttribute('placeholder', 'Ask about this passage…');
	await input.fill('Quickly relative to what?');
	await input.press('Enter');
	await expect(sideThread(page).getByTestId('side-pending-quote')).toHaveCount(0);
	const learner = sideThread(page).getByTestId('side-learner-message');
	await expect(learner).toContainText('derivative describes how quickly');
	await expect(learner).toContainText('Quickly relative to what?');
	await expect(sideThread(page).getByTestId('side-helper-message')).toContainText(
		'per unit of the input'
	);
});
