import { test, expect } from '../fixtures';
import { askSideQuestion, sideThread, startTaughtLesson } from '../side-chat';
import { sendLessonMessage } from '../teaching';

test.use({ script: 'verify/scripts/side-chat-current-step.json' });

test('side-chat-current-step', async ({ page }, testInfo) => {
	await startTaughtLesson(page, 'First step');
	await page.getByTestId('side-conversation-button').click();
	await askSideQuestion(page, 'What is instantaneous change?');
	await expect(sideThread(page).getByTestId('side-helper-message')).toContainText('speedometer');
	await expect(page.getByTestId('side-current-step')).toHaveCount(0);

	await sendLessonMessage(page, 'Continue');
	await expect(page.getByText('Second step', { exact: false })).toBeVisible();
	await expect(page.getByTestId('side-conversation-button')).toHaveCount(2);
	await expect(page.getByTestId('side-current-step')).toBeVisible();
	await expect(sideThread(page).getByTestId('side-helper-message')).toContainText('speedometer');
	await page.screenshot({ path: testInfo.outputPath('off-current.png'), animations: 'disabled' });

	await page.getByTestId('side-current-step').click();
	await expect(page.getByTestId('side-current-step')).toHaveCount(0);
	await expect(sideThread(page).getByTestId('side-learner-message')).toHaveCount(0);
	await expect(sideThread(page).getByTestId('side-thread-input')).toHaveAttribute(
		'placeholder',
		'Ask a side question…'
	);

	await page.getByTestId('side-conversation-button').first().click();
	await expect(page.getByTestId('side-current-step')).toBeVisible();
	await sideThread(page).getByRole('button', { name: 'Close side conversation' }).click();
	await expect(page.getByTestId('side-current-step')).toHaveCount(0);

	await page.keyboard.press('Control+j');
	await expect(page.getByRole('button', { name: 'Toggle right panel' })).toHaveAttribute(
		'aria-expanded',
		'false'
	);
	await page.keyboard.press('Control+j');
	await expect(page.getByRole('tab', { name: 'Side chat' })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await expect(sideThread(page).getByTestId('side-thread-input')).toBeFocused();
	await page.keyboard.press('Control+j');
	await expect(sideThread(page)).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Toggle right panel' })).toHaveAttribute(
		'aria-expanded',
		'false'
	);
});
