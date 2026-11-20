import { test, expect } from './fixtures';
import { startLesson } from './questions';

test.use({ script: 'verify/scripts/question-reload.json' });

test('question-reload', async ({ page, request, appendEntries }) => {
	await startLesson(page);
	const dock = page.getByTestId('question-dock');
	await expect(dock.getByText('What is the slope of a horizontal line?')).toBeVisible();
	const order = (await dock.getByRole('radio').allTextContents()).map((label) => label.trim());
	await page.reload();
	await expect(dock.getByRole('radio')).toHaveText(order);
	const id = new URL(page.url()).pathname.split('/').at(-1)!;
	const saved = await (await request.get(`/api/sessions/${id}`)).json();
	const call = saved.entries.at(-1).parts.at(-1);
	const args = typeof call.arguments === 'string' ? JSON.parse(call.arguments) : call.arguments;
	await appendEntries(id, [
		{
			kind: 'tool_result',
			tool_name: 'probe',
			tool_call_id: call.tool_call_id,
			is_error: false,
			text: '{"kind":"quiz","dontKnow":true}',
			details: {
				kind: 'quiz',
				tool: 'probe',
				question_text: args.question,
				dont_know: true,
				options: order.map((label, i) => ({ index: i + 1, label })),
				answers: [],
				correct: false,
				correct_indices: [order.indexOf('Zero') + 1],
				explanation: args.explanation,
				answered_at: new Date().toISOString()
			}
		}
	]);
	const continued = page.waitForRequest(
		(request) =>
			request.method() === 'POST' &&
			request.url().endsWith('/input') &&
			request.postDataJSON().type === 'continue'
	);
	await page.reload();
	await continued;
	const card = page.getByTestId('answered-card');
	await expect(card).toContainText("didn't know");
	await expect(card.getByLabel('Correct option')).toBeVisible();
	await expect(page.getByText('I picked up your saved answer.')).toBeInViewport();
});
