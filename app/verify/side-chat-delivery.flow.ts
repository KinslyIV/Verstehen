import { test, expect } from './fixtures';
import { askSideQuestion, sideThread, startTaughtLesson } from './side-chat';
import { sendLessonMessage } from './teaching';

test.use({ script: 'verify/scripts/side-chat-delivery.json' });

test('side-chat-delivery', async ({ page, request }) => {
	await startTaughtLesson(page, 'A derivative describes how quickly');
	await page.getByTestId('side-conversation-button').click();
	await askSideQuestion(page, 'What does instantaneous mean?');
	await expect(sideThread(page).getByTestId('side-helper-message')).toContainText(
		'slope of the tangent line'
	);
	await expect(sideThread(page).getByTestId('side-streaming-answer')).toHaveCount(0);

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
		expect.stringMatching(/^exchange_side_.*_update_2$/)
	]);
	expect(markers[0].display).toBe(false);
	expect(markers[0].content).toContain('Learner:\nWhat does instantaneous mean?');
	expect(markers[1].content).toContain('Helper:\nA **derivative** is the slope');
});
