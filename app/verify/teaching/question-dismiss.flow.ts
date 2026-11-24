import { test, expect } from '../fixtures';
import { startLesson } from '../questions';

test.use({ script: 'verify/scripts/question-dismiss.json' });

test('question-dismiss', async ({ page, request }) => {
	await startLesson(page);
	await expect(page.getByTestId('question-dock')).toBeVisible();
	await page.getByRole('button', { name: 'Choose model' }).click();
	await page.keyboard.press('Escape');
	await expect(page.getByRole('dialog', { name: 'Dismiss this question?' })).toHaveCount(0);
	await page.keyboard.press('Escape');
	const dialog = page.getByRole('dialog', { name: 'Dismiss this question?' });
	await expect(dialog).toContainText('Skipped — the teacher moves on without it.');
	await page.keyboard.press('Escape');
	await expect(dialog).toHaveCount(0);
	await page.keyboard.press('Escape');
	await dialog.getByRole('button', { name: 'Dismiss', exact: true }).click();
	await expect(page.getByTestId('answered-card')).toHaveText(
		'What is the slope of a horizontal line? — skipped'
	);
	const session = new URL(page.url()).pathname.replace('/session/', '/sessions/');
	const saved = await (await request.get(`/api${session}`)).json();
	expect(saved.turn_in_flight).toBe(false);
	expect(saved.entries.at(-1).details.dismissed).toBe(true);
	await page
		.getByRole('textbox', { name: 'What do you want to learn?' })
		.fill('Can we talk about velocity?');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByText('Let’s work on the new topic.')).toBeVisible();
});
