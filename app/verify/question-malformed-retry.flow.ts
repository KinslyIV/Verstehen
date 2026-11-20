import { test, expect } from './fixtures';

test.use({ script: 'verify/scripts/question-malformed-retry.json' });

test('question-malformed-retry', async ({ page, request, appendEntries }) => {
	const session = await request.post('/api/sessions', { data: { title: 'Recovered lesson' } });
	expect(session.ok()).toBe(true);
	const { id } = await session.json();
	await appendEntries(id, [
		{ kind: 'user', text: 'Teach me about derivatives' },
		{
			kind: 'assistant',
			stop_reason: 'length',
			parts: [
				{
					type: 'tool_call',
					tool_call_id: 'truncated-probe',
					tool_name: 'probe',
					arguments: '{"question":'
				}
			]
		}
	]);
	await page.goto(`/session/${id}`);
	await expect(
		page.getByText('This question could not be displayed. Retry it or send a message to continue.')
	).toBeVisible();
	await page.getByRole('button', { name: 'Retry question' }).click();
	await expect(page.getByTestId('question-dock')).toContainText(
		'Replacement: What is the slope of a horizontal line?'
	);
	await expect(page.getByRole('button', { name: 'Retry question' })).toHaveCount(0);
});
