import { test, expect } from '../fixtures';
import { askSideQuestion, sideThread, startTaughtLesson } from '../side-chat';

test.use({ script: 'verify/scripts/side-chat-reload.json' });

test('side-chat-reload', async ({ page }) => {
	await startTaughtLesson(page, 'A derivative describes how quickly');
	await page.getByTestId('side-conversation-button').click();
	await askSideQuestion(page, 'What is a derivative at a point?');
	await expect(sideThread(page).getByTestId('side-streaming-answer')).toBeVisible();
	await page.reload();
	await page.getByRole('button', { name: 'Toggle right panel' }).click();
	await page.getByRole('tab', { name: 'Side chat' }).click();
	await expect(sideThread(page).getByTestId('side-learner-message')).toContainText(
		'What is a derivative at a point?'
	);
	await expect(sideThread(page).getByTestId('side-streaming-answer')).toBeVisible();
	await expect(sideThread(page).getByTestId('side-helper-message')).toContainText(
		'limit of secant slopes',
		{ timeout: 15_000 }
	);
	await expect(sideThread(page).getByTestId('side-streaming-answer')).toHaveCount(0);
	await expect(page.getByTestId('side-conversation-button')).toHaveAttribute(
		'data-has-history',
		'true'
	);
});
