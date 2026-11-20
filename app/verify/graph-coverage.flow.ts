import { test, expect } from './fixtures';
import { createSession } from './compaction';
import { scriptExtractors, setGraphSettings } from './graph';

test.use({ script: 'verify/scripts/graph-coverage.json' });

const prose =
	'We compared the slopes of lines and then the average rate of change of a curve between two points. '.repeat(
		26
	);

test('graph-coverage', async ({ page, request, appendEntries }) => {
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

	// The ring is full: the next run is due.
	const ring = page.getByTestId('coverage-ring');
	await expect(ring).toHaveAttribute('data-fill', '1.00');
	await ring.click();
	const popover = page.getByTestId('coverage-ring-popover');
	await expect(popover).toContainText('Uncovered');
	await expect(popover).toContainText('Chunk threshold');
	await expect(popover).toContainText('500 tokens');
	await page.screenshot({ path: test.info().outputPath('ring.png'), animations: 'disabled' });

	// Extract now starts a run; the Jobs tab lists it with End.
	await page.getByTestId('coverage-extract').click();
	await expect(popover.getByTestId('coverage-extract')).toHaveText('Running');
	await page.keyboard.press('Escape');
	await page.getByRole('button', { name: 'Toggle right panel' }).click();
	await page.getByRole('tab', { name: 'Jobs' }).click();
	const row = page.getByTestId('extraction-row');
	await expect(row).toContainText('Extraction —');
	await expect(row.getByTestId('extraction-elapsed')).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('jobs.png'), animations: 'disabled' });
	await row.getByTestId('extraction-end').click();
	await expect(row).toHaveCount(0);
	await expect(ring).toHaveAttribute('data-fill', '1.00');

	// The session menu shows the same numbers; Extract now finishes the job.
	await page.getByRole('link', { name: /Slope of a curve/ }).click({ button: 'right' });
	const block = page.getByTestId('ctx-coverage');
	await expect(block).toContainText('tok uncovered');
	await page.screenshot({ path: test.info().outputPath('menu.png'), animations: 'disabled' });
	await block.getByTestId('ctx-extract').click();
	await expect(block).toContainText('fully extracted', { timeout: 30_000 });
	await page.keyboard.press('Escape');
	await expect(ring).toHaveAttribute('data-fill', '0.00');
	const graph = await (await request.get('/api/graph')).json();
	expect(graph.propositions.map((p: { name: string }) => p.name).sort()).toEqual([
		'Average rate',
		'Secant slope'
	]);
});
