import { test, expect } from '../fixtures';
import { demoGraph, setGraphSettings, sessionIds } from '../graph';

test.use({ script: 'verify/scripts/practice-graph.json' });

const poseEntries = [
	{
		kind: 'assistant',
		entry_id: 'seed-pose',
		stop_reason: 'stop',
		parts: [
			{
				type: 'tool_call',
				tool_call_id: 'seed-problem',
				tool_name: 'problem',
				arguments: {
					statement: 'Differentiate $x^2$.',
					mode: 'recall',
					modelSolution: '$2x$.'
				}
			}
		]
	},
	{
		kind: 'tool_result',
		entry_id: 'seed-ack',
		tool_call_id: 'seed-problem',
		tool_name: 'problem',
		text: 'Problem posed.',
		is_error: false
	}
] as never;

test('practice-graph-and-sidebar', async ({ page, request, seedGraph, appendEntries }) => {
	const seed = await demoGraph(request);
	const created = await request.post('/api/sessions', {
		data: { title: 'Power rule drills', kind: 'practice' }
	});
	const practiceId = (await created.json()).id;
	seed.nodes.push({
		id: 'n_pr1',
		name: 'Practiced rule',
		statement: 'Born in a practice session.',
		session: practiceId
	});
	seed.chains.push({ id: 'arg_pr', premises: ['n_pr1'], conclusion: 'n_pr1', session: practiceId });
	await seedGraph(seed);
	await appendEntries(practiceId, poseEntries);

	// The sidebar tells practice rows apart and filters by kind.
	await page.goto('/session/new');
	const practiceRow = page.getByRole('link', { name: /Power rule drills/ });
	await expect(practiceRow).toContainText('Problem waiting');
	await expect(practiceRow.getByLabel('Practice session')).toBeVisible();
	await expect(page.getByRole('link', { name: /Derivatives/ })).toBeVisible();
	await page.screenshot({
		path: test.info().outputPath('sidebar-all.png'),
		animations: 'disabled'
	});
	await page.getByTestId('kind-filter-practice').click();
	await expect(page.getByRole('link', { name: /Derivatives/ })).toHaveCount(0);
	await page.reload();
	await expect(page.getByTestId('kind-filter-practice')).toHaveAttribute('aria-pressed', 'true');
	await expect(practiceRow).toBeVisible();
	await page.screenshot({
		path: test.info().outputPath('sidebar-practice.png'),
		animations: 'disabled'
	});
	await page.getByTestId('kind-filter-teach').click();
	await expect(practiceRow).toHaveCount(0);
	await expect(page.getByRole('link', { name: /Derivatives/ })).toBeVisible();
	await page.getByTestId('kind-filter-all').click();

	// A practice row has no graph-traces option when deleted.
	await practiceRow.click({ button: 'right' });
	await page.getByRole('menuitem', { name: 'Delete' }).click();
	await expect(page.getByTestId('delete-session-dialog')).toContainText('Power rule drills');
	await expect(page.getByTestId('delete-traces')).toHaveCount(0);
	await page.screenshot({ path: test.info().outputPath('delete.png'), animations: 'disabled' });
	await page.getByTestId('delete-cancel').click();

	// The graph offers both starts for picked nodes, and practice sessions are not chain sources.
	await page.goto('/graph');
	await expect(page.getByTestId('start-teaching')).toHaveCount(0);
	await page.getByTestId('node-picker-chip').click();
	await expect(page.getByTestId('chain-table')).toContainText('Derivatives');
	await expect(page.getByTestId(`cluster-toggle-${practiceId}`)).toHaveCount(0);
	await page.getByTestId('cluster-checkbox-src_limits').check();
	await page.getByTestId('chain-pick-done').click();
	await expect(page.getByTestId('start-teaching')).toBeVisible();
	await expect(page.getByTestId('start-practice')).toBeVisible();
	await page.screenshot({
		path: test.info().outputPath('graph-picked.png'),
		animations: 'disabled'
	});
	await page.getByTestId('start-practice').click();
	await expect(page).toHaveURL(/\/session\/new\?mode=practice$/);
	await expect(page.getByTestId('node-picker-chip')).toContainText('3 nodes selected');

	// The mode toggle keeps the draft and the picks.
	const draft = page.getByRole('textbox', { name: 'What do you want to learn?' });
	await draft.fill('Continuity');
	await page.getByTestId('kind-teach').click();
	await expect(page).toHaveURL(/\/session\/new$/);
	await expect(draft).toHaveValue('Continuity');
	await expect(page.getByTestId('node-picker-chip')).toContainText('3 nodes selected');
	await page.getByTestId('kind-practice').click();
	await expect(page).toHaveURL(/\/session\/new\?mode=practice$/);
	await expect(draft).toHaveValue('Continuity');
	await page.screenshot({
		path: test.info().outputPath('new-practice.png'),
		animations: 'disabled'
	});
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/(?!new)[^/]+$/);

	// The thread carries the picks as a collapsed graph-context card.
	const context = page.getByTestId('graph-context-card');
	await expect(context.getByTestId('graph-context-toggle')).toHaveText(
		/Graph context\s*3 propositions · 1 chain/
	);
	await expect(page.getByTestId('graph-context-body')).toHaveCount(0);
	await context.getByTestId('graph-context-toggle').click();
	await expect(page.getByTestId('graph-context-body')).toContainText('Continuity');
	await expect(page.getByTestId('practice-dock')).toContainText('continuous at');
	await page.screenshot({ path: test.info().outputPath('thread.png'), animations: 'disabled' });
	await page
		.getByTestId('practice-dock')
		.getByRole('textbox', { name: 'Your thinking' })
		.fill('Both sides approach 0.');
	await page.keyboard.press('Enter');
	await expect(page.getByTestId('conclude-outcome')).toHaveText('Solved with hints');
	await page.getByTestId('metadata-toggle').click();
	await expect(page.getByTestId('metadata-box')).toContainText('Continuity');
	await page.screenshot({ path: test.info().outputPath('metadata.png'), animations: 'disabled' });

	// The knowledge summary counts practice sessions apart; the chains table leaves them out.
	await setGraphSettings(request, { rendering: false });
	await page.goto('/graph');
	const summary = page.getByTestId('knowledge-summary');
	await expect(summary).toContainText('3 teaching sessions');
	await expect(summary).toContainText('2 practice sessions');
	await page.screenshot({ path: test.info().outputPath('summary.png'), animations: 'disabled' });
	await page.getByTestId('open-chain-table').click();
	await expect(page.getByTestId('chain-table')).toContainText('13 chains · 18 nodes');
	await expect(
		page.getByTestId(`cluster-toggle-${(await sessionIds(request))['Power rule drills']}`)
	).toHaveCount(0);
	await page.screenshot({ path: test.info().outputPath('chains.png'), animations: 'disabled' });
});
