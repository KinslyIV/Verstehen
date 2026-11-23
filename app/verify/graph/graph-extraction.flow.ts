import { test, expect } from '../fixtures';
import { createSession } from '../compaction';
import { scriptExtractors, setGraphSettings, waitForLayout } from '../graph';

test.use({ script: 'verify/scripts/graph-extraction.json' });

const prose = `${'We compared the slopes of lines and then the average rate of change of a curve between two points. '.repeat(26)}`;

test('graph-extraction', async ({ page, request, appendEntries }) => {
	await scriptExtractors(request);
	await setGraphSettings(request, { extraction_chunk_tokens: 500 });
	const id = await createSession(request, 'Slope of a curve');
	await appendEntries(id, [
		{ kind: 'user', entry_id: 'seed-learner', text: 'Teach me about derivatives' },
		{
			kind: 'assistant',
			entry_id: 'seed-teacher',
			stop_reason: 'stop',
			parts: [{ type: 'text', text: prose }]
		}
	]);
	await page.goto(`/session/${id}`);
	const coverage = page.waitForEvent(
		'requestfinished',
		(req) =>
			req.method() === 'GET' && new URL(req.url()).pathname === `/api/sessions/${id}/coverage`
	);
	await page.getByRole('textbox', { name: 'What do you want to learn?' }).fill('Keep going');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByText('Let’s keep going with the slope of a curve.')).toBeVisible();
	expect((await (await coverage).response())?.status()).toBe(200);

	await page.getByRole('link', { name: 'Knowledge graph' }).click();
	await expect(page.getByTestId('pipeline-pill').first()).toContainText('Slope of a curve');
	await page.screenshot({ path: test.info().outputPath('running.png'), animations: 'disabled' });

	await expect(page.getByTestId('graph-canvas')).toBeVisible({ timeout: 30_000 });
	await expect(page.getByTestId('pipeline-pill')).toHaveCount(0, { timeout: 30_000 });
	await waitForLayout(request, 5);
	const graph = await (await request.get('/api/graph')).json();
	expect(graph.propositions.map((p: { name: string }) => p.name).sort()).toEqual([
		'Average rate',
		'Derivative',
		'Instantaneous rate',
		'Secant slope'
	]);
	expect(graph.clusters).toHaveLength(1);
	expect(graph.clusters[0].label).toBe('Slope of a curve');
	await expect(page.getByRole('button', { name: 'Graph costs' })).toBeVisible();
	await page.waitForTimeout(800);
	await page.screenshot({ path: test.info().outputPath('graph.png'), animations: 'disabled' });
	await page.getByRole('button', { name: 'Graph costs' }).click();
	await expect(page.getByRole('dialog', { name: 'Graph pipeline costs' })).toContainText(
		'Slope of a curve'
	);
	await page.screenshot({ path: test.info().outputPath('costs.png'), animations: 'disabled' });
});
