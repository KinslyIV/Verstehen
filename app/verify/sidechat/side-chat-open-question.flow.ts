import { test, expect } from '../fixtures';
import { askSideQuestion, sideThread } from '../side-chat';
import { startLesson } from '../questions';

test.use({ script: 'verify/scripts/side-chat-open-question.json' });

test('side-chat-open-question', async ({ page }) => {
	await startLesson(page);
	const dock = page.getByTestId('question-dock');
	await expect(dock.getByText('What is the slope of a horizontal line?')).toBeVisible();
	await dock.getByRole('textbox', { name: 'Your thinking' }).fill('The line is flat.');
	await page.getByTestId('side-conversation-button').click();
	const asked = page.waitForRequest(
		(request) => request.method() === 'POST' && request.url().endsWith('/side-chats')
	);
	await askSideQuestion(page, 'Can I get a nudge?');
	expect((await asked).postDataJSON()).toMatchObject({
		text: 'Can I get a nudge?',
		working: 'The line is flat.'
	});
	await expect(sideThread(page).getByTestId('side-helper-message')).toContainText(
		'what stays the same'
	);
	await expect(dock.getByRole('textbox', { name: 'Your thinking' })).toHaveValue(
		'The line is flat.'
	);
});
