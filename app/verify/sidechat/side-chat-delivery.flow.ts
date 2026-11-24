import { test, expect } from '../fixtures';
import { askSideQuestion, sideThread, startTaughtLesson } from '../side-chat';
import { sendLessonMessage } from '../teaching';

test.use({ script: 'verify/scripts/side-chat-delivery.json' });

test('side-chat-delivery', async ({ page, request }) => {
	await startTaughtLesson(page, 'A derivative describes how quickly');
	const button = page.getByTestId('side-conversation-button');
	await expect(button).toHaveAttribute('data-has-history', 'false');
	await expect(button).toHaveAccessibleName('Ask a side question');
	await button.click();
	await expect(page.getByRole('tab', { name: 'Side chat' })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	const input = sideThread(page).getByTestId('side-thread-input');
	await expect(input).toBeFocused();
	await expect(input).toHaveAttribute('placeholder', 'Ask a side question…');
	await askSideQuestion(page, 'What does instantaneous mean?');
	await expect(sideThread(page).getByTestId('side-learner-message')).toContainText(
		'What does instantaneous mean?'
	);
	await expect(sideThread(page).getByTestId('side-streaming-answer')).toBeVisible();
	await expect(sideThread(page).getByTestId('side-helper-message')).toContainText(
		'slope of the tangent line'
	);
	await expect(sideThread(page).getByTestId('side-streaming-answer')).toHaveCount(0);
	await expect(input).toHaveAttribute('placeholder', 'Ask a follow-up…');
	await expect(button).toHaveAttribute('data-has-history', 'true');
	await expect(button).toHaveAccessibleName('Open side conversation');
	await expect(page.getByTestId('side-current-step')).toHaveCount(0);

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
	const quote = sideThread(page).getByTestId('side-pending-quote');
	await expect(quote).toHaveText('derivative describes how quickly');
	await expect(input).toHaveAttribute('placeholder', 'Ask about this passage…');
	await input.fill('Quickly relative to what?');
	await input.press('Enter');
	await expect(sideThread(page).getByTestId('side-pending-quote')).toHaveCount(0);
	const secondLearner = sideThread(page).getByTestId('side-learner-message').nth(1);
	await expect(secondLearner).toContainText('derivative describes how quickly');
	await expect(secondLearner).toContainText('Quickly relative to what?');
	await expect(sideThread(page).getByTestId('side-helper-message').nth(1)).toContainText(
		'per unit of the input'
	);

	await sendLessonMessage(page, 'Ready to go on');
	await expect(page.getByText('that tangent slope is exactly where we go next')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();

	await expect(page.getByText('Recorded learner–helper conversation update')).toHaveCount(0);
	const id = page.url().split('/').pop();
	const { entries } = await (await request.get(`/api/sessions/${id}`)).json();
	const markers = entries.filter(
		(entry: { kind: string; marker_type?: string }) =>
			entry.kind === 'marker' && entry.marker_type === 'side-question'
	);
	expect(markers.map((marker: { entry_id: string }) => marker.entry_id)).toEqual([
		expect.stringMatching(/^exchange_side_.*_update_1$/),
		expect.stringMatching(/^exchange_side_.*_update_2$/),
		expect.stringMatching(/^exchange_side_.*_update_3$/),
		expect.stringMatching(/^exchange_side_.*_update_4$/)
	]);
	expect(markers[0].display).toBe(false);
	expect(markers[0].content).toContain('Learner:\nWhat does instantaneous mean?');
	expect(markers[1].content).toContain('Helper:\nA **derivative** is the slope');
	expect(markers[2].content).toContain('Quoted tutor passage:\nderivative describes how quickly');
	expect(markers[2].content).toContain('Learner:\nQuickly relative to what?');
	expect(markers[3].content).toContain('Helper:\nIt is how much the output changes');
});
