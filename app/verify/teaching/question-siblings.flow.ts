import { test, expect } from '../fixtures';
import { selectOption, startLesson } from '../questions';

test.use({ script: 'verify/scripts/question-siblings.json' });

test('question-siblings', async ({ page, request }) => {
	await startLesson(page);
	const dock = page.getByTestId('question-dock');
	await selectOption(page, 'Zero');
	await dock.getByRole('button', { name: 'Submit answer' }).click();
	await expect(dock.getByText('Which graph would you like to see next?')).toBeVisible();
	const session = new URL(page.url()).pathname;
	const saved = await (
		await request.get(`/api${session.replace('/session/', '/sessions/')}`)
	).json();
	expect(saved.turn_in_flight).toBe(false);
	expect(saved.entries.map((entry: { kind: string }) => entry.kind)).toEqual([
		'user',
		'assistant',
		'tool_result'
	]);
	await dock.getByRole('textbox', { name: 'Your answer' }).fill('A line');
	await dock.getByRole('button', { name: 'Submit answer' }).click();
	await expect(page.getByTestId('answered-card')).toHaveCount(2);
	await expect(page.getByText('Thanks for answering both questions.')).toBeVisible();
});
