import { test, expect } from './fixtures';
import { askSideQuestion, sideThread, startTaughtLesson } from './side-chat';

test.use({ script: 'verify/scripts/side-chat-ask.json' });

for (const theme of ['dark', 'light']) {
	test(`side-chat-ask-${theme}`, async ({ page }) => {
		await page.addInitScript((value) => localStorage.setItem('mode-watcher-mode', value), theme);
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
	});
}
