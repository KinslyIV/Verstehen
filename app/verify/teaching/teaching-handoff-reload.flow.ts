import { test, expect } from '../fixtures';
import { waitForPlan } from '../teaching';

test.use({ script: 'verify/scripts/teaching-handoff-reload.json' });

test('teaching-handoff-reload', async ({ page, request, appendEntries }) => {
	const created = await request.post('/api/sessions', { data: { title: 'Teach me derivatives' } });
	expect(created.ok()).toBe(true);
	const { id } = await created.json();
	await page.goto(`/session/${id}`);
	await expect(page.getByTestId('phase-chip')).toHaveText('Probing');
	await appendEntries(id, [
		{ kind: 'user', text: 'Teach me derivatives' },
		{
			kind: 'assistant',
			stop_reason: 'stop',
			parts: [
				{
					type: 'tool_call',
					tool_call_id: 'assessment',
					tool_name: 'probe_done',
					arguments: {
						assessment: { strands: [{ strand: 'Slope', assessment: 'Can compare two slopes.' }] }
					}
				}
			]
		},
		{
			kind: 'tool_result',
			tool_call_id: 'assessment',
			tool_name: 'probe_done',
			is_error: false,
			text: 'Assessment recorded.',
			details: { ok: true }
		}
	]);
	const handoff = page.waitForRequest(
		(request) =>
			request.method() === 'POST' &&
			request.url().endsWith('/input') &&
			request.postDataJSON().type === 'handoff'
	);
	await page.reload();
	await handoff;
	await expect(page.getByTestId('phase-divider-plan')).toBeVisible();
	await waitForPlan(page);
	await page.reload();
	await expect(page.getByTestId('phase-divider-plan')).toHaveCount(1);
	await expect(page.getByTestId('plan-block')).toHaveCount(1);
	await page.getByTestId('plan-block').click();
	await waitForPlan(page);
});
