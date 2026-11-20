import { test, expect } from './fixtures';
import { demoGraph, nodePoint, sessionIds, waitForLayout } from './graph';

test.use({ script: 'none' });

test('graph-delete', async ({ page, request, seedGraph }) => {
	await seedGraph(await demoGraph(request));
	const ids = await sessionIds(request);
	const nodeIds = async () =>
		(await (await request.get('/api/graph')).json()).nodes.map((n: { id: string }) => n.id);
	await page.goto('/graph');
	await waitForLayout(request, 22);

	// Right-click a node: the menu's one action is Delete.
	const point = await nodePoint(page, request, 'n_a5');
	await page.mouse.click(point.x, point.y, { button: 'right' });
	await page.getByTestId('ctx-node-delete').click();
	const dialog = page.getByTestId('delete-node-dialog');
	await expect(dialog).toContainText('Delete node?');
	await expect(dialog).toContainText('Rate units');
	await expect(dialog).toContainText('This permanently deletes the node — this cannot be undone.');
	await page.screenshot({
		path: test.info().outputPath('node-dialog.png'),
		animations: 'disabled'
	});
	await page.getByTestId('node-delete-confirm').click();
	await expect(dialog).toHaveCount(0);
	await expect.poll(nodeIds).not.toContain('n_a5');

	// The detail card has Delete too.
	const other = await nodePoint(page, request, 'n_b5');
	await page.mouse.click(other.x, other.y);
	await page.getByTestId('card-delete').click();
	await expect(dialog).toContainText('Sum rule');
	await page.getByTestId('node-delete-confirm').click();
	await expect(dialog).toHaveCount(0);
	await expect.poll(nodeIds).not.toContain('n_b5');
	await expect(page.getByTestId('node-card')).toHaveCount(0);

	// A source from the chains table: its contributions go with it.
	await page.getByTestId('open-chain-table').click();
	await page.getByTestId('cluster-checkbox-src_limits').check();
	await expect(page.getByTestId('chain-selected-summary')).toContainText('1 source');
	await page.getByTestId('chain-delete').click();
	const sourceDialog = page.getByTestId('delete-source-dialog');
	await expect(sourceDialog).toContainText('limits');
	await expect(sourceDialog).toContainText('Removes these sources’ contributions');
	await expect(page.getByTestId('delete-source-sessions')).toHaveCount(0);
	await page.screenshot({
		path: test.info().outputPath('source-dialog.png'),
		animations: 'disabled'
	});
	await page.getByTestId('source-delete-confirm').click();
	await expect(sourceDialog).toHaveCount(0);
	await expect(page.getByTestId('cluster-group-src_limits')).toHaveCount(0);
	await expect.poll(nodeIds).not.toContain('n_d1');
	await page.getByTestId('chain-table-close').click();

	// A session, with its graph traces: its own nodes go, shared knowledge stays.
	await page.getByRole('link', { name: /Integrals/ }).click({ button: 'right' });
	await page.getByRole('menuitem', { name: 'Delete' }).click();
	const sessionDialog = page.getByTestId('delete-session-dialog');
	await expect(sessionDialog).toContainText('Also remove its graph traces');
	await page.getByTestId('delete-traces-checkbox').check();
	await page.screenshot({
		path: test.info().outputPath('session-dialog.png'),
		animations: 'disabled'
	});
	await page.getByTestId('delete-confirm').click();
	await expect(sessionDialog).toHaveCount(0);
	await expect.poll(nodeIds).not.toContain('n_c1');
	expect(await nodeIds()).toContain('n_b3');

	// Without the box the session goes and the graph keeps what it learned.
	await page.getByRole('link', { name: /Slope and rates/ }).click({ button: 'right' });
	await page.getByRole('menuitem', { name: 'Delete' }).click();
	await page.getByTestId('delete-confirm').click();
	await expect(sessionDialog).toHaveCount(0);
	await expect(page.getByRole('link', { name: /Slope and rates/ })).toHaveCount(0);
	expect(await nodeIds()).toContain('n_a1');
	expect(ids.Derivatives).toBeTruthy();
});
