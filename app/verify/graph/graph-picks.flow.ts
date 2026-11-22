import { test, expect } from '../fixtures';
import { demoGraph, sessionIds } from '../graph';

test.use({ script: 'verify/scripts/session.json' });

test('graph-picks', async ({ page, request, seedGraph }) => {
	await seedGraph(await demoGraph(request));
	await page.goto('/graph');
	await expect(page.getByTestId('start-session')).toHaveCount(0);
	await page.getByTestId('node-picker-chip').click();
	const table = page.getByTestId('chain-table');
	const derivatives = (await sessionIds(request)).Derivatives;
	await page.getByTestId(`cluster-toggle-${derivatives}`).click();
	await page.getByTestId('chain-checkbox-arg_ch2').check();
	await expect(page.getByTestId('chain-selected-summary')).toContainText('3 nodes → 2 chains');
	await page.getByTestId('chain-pick-done').click();
	await expect(table).toHaveCount(0);
	await expect(page.getByTestId('node-picker-chip')).toContainText('3 nodes selected');
	await page.screenshot({
		path: test.info().outputPath('graph-picked.png'),
		animations: 'disabled'
	});

	// Start session keeps the picks on the new-session screen.
	await page.getByTestId('start-session').click();
	await expect(page).toHaveURL(/\/session\/new$/);
	await expect(page.getByTestId('node-picker-chip')).toContainText('3 nodes selected');
	await page.screenshot({
		path: test.info().outputPath('new-session.png'),
		animations: 'disabled'
	});

	// The chip reopens the table, and Clear empties it.
	await page.getByTestId('node-picker-chip').click();
	await page.getByTestId('chain-clear').click();
	await expect(page.getByTestId('node-picker-chip')).toContainText('Pick nodes');
	await page.getByTestId('chain-table-close').click();

	// Pick one node here, then send: the session starts with the hidden marker.
	await page.getByTestId('node-picker-chip').click();
	await page.getByTestId('cluster-checkbox-src_limits').check();
	await expect(page.getByTestId('chain-selected-summary')).toContainText('3 nodes → 1 chain');
	await page.getByTestId('chain-pick-done').click();
	await page.getByRole('textbox', { name: 'What do you want to learn?' }).fill('Teach me limits');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/(?!new)[^/]+$/);
	await expect(page.getByText('A derivative describes how quickly')).toBeVisible();
	await expect(page.getByText('[Session context]')).toHaveCount(0);
	const id = page.url().split('/').at(-1)!;
	const session = await (await request.get(`/api/sessions/${id}`)).json();
	expect(session.entries[0]).toMatchObject({ kind: 'marker', marker_type: 'graph-context' });
	expect(session.entries[0].content).toContain('Limit: A limit is the value a function approaches');
	expect(session.entries[0].content).toContain('Limit, One-sided limit → Continuity');
	expect(session.entries[1]).toMatchObject({ kind: 'user', text: 'Teach me limits' });
	await page.getByRole('link', { name: 'New session' }).click();
	await expect(page.getByTestId('node-picker-chip')).toContainText('Pick nodes');
});
