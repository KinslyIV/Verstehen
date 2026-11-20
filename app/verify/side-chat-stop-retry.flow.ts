import { test, expect } from './fixtures';
import { askSideQuestion, sideThread, startTaughtLesson } from './side-chat';

test.use({ script: 'verify/scripts/side-chat-stop-retry.json' });

test('side-chat-stop-retry', async ({ page }, testInfo) => {
	await startTaughtLesson(page, 'A derivative describes how quickly');
	await page.getByTestId('side-conversation-button').click();
	await askSideQuestion(page, 'What is slope?');
	await expect(sideThread(page).getByTestId('side-streaming-answer')).toContainText(
		'Slope is rise'
	);
	await sideThread(page).getByRole('button', { name: 'Stop side answer' }).click();
	const stopped = sideThread(page).getByTestId('side-helper-message');
	await expect(stopped).toContainText('Slope is rise');
	await expect(stopped).toContainText('Stopped');
	await expect(sideThread(page).getByRole('button', { name: 'Send side question' })).toBeVisible();

	await askSideQuestion(page, 'Try once more');
	await expect(sideThread(page).getByText('Scripted helper failure')).toBeVisible();
	const retry = sideThread(page).getByRole('button', { name: 'Retry answer' });
	await expect(retry).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('failed.png'), animations: 'disabled' });
	await retry.click();
	await expect(sideThread(page).getByTestId('side-helper-message').last()).toContainText(
		'Retry worked: slope is the change in height per step across.'
	);
	await expect(sideThread(page).getByRole('button', { name: 'Send side question' })).toBeVisible();
	await expect(retry).toHaveCount(0);
});
