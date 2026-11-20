import { test, expect } from './fixtures';
import { demoGraph, sessionIds } from './graph';

test.use({ script: 'none' });

test('graph-chains-table', async ({ page, request, seedGraph }) => {
	await seedGraph(await demoGraph(request));
	const ids = await sessionIds(request);
	await page.goto('/graph');
	await page.getByTestId('open-chain-table').click();
	const table = page.getByTestId('chain-table');
	await expect(table).toContainText('13 chains · 17 nodes');
	const groups = table.locator('[data-testid^="cluster-group-"]');
	await expect(groups).toHaveCount(4);
	await expect(table.locator('[data-testid^="chain-block-"]')).toHaveCount(0);

	// Source → chain → statements, one click each.
	await page.getByTestId(`cluster-toggle-${ids.Derivatives}`).click();
	await expect(table.locator('[data-testid^="chain-block-"]')).toHaveCount(6);
	await page.getByTestId('chain-toggle-arg_ch2').click();
	await expect(page.getByTestId('chain-and-arg_ch2-1')).toBeVisible();
	await expect(page.getByTestId('chain-implies-arg_ch2')).toBeVisible();
	await expect(page.getByTestId('prop-row-n_a2')).toContainText('average rate of change');
	await expect(page.getByTestId('prop-row-n_b1')).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('expanded.png'), animations: 'disabled' });

	// Sort: Props starts largest-first, a second click flips it.
	await page.getByTestId('sort-props').click();
	await expect(page.getByTestId('sort-props')).toHaveAttribute('data-sort', 'descending');
	await expect(groups.first()).toContainText('Derivatives');
	await page.getByTestId('sort-props').click();
	await expect(groups.last()).toContainText('Derivatives');
	await page.getByTestId('sort-name').click();
	await expect(groups.first()).toContainText('Derivatives');

	// Search opens the matching source on its own.
	await page.getByTestId('chain-table-search').fill('riemann');
	await expect(groups).toHaveCount(1);
	await expect(groups.first()).toContainText('Integrals');
	await expect(page.getByTestId('chain-row-arg_ch6')).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('search.png'), animations: 'disabled' });
	await page.getByTestId('chain-table-search').fill('');
	await expect(groups).toHaveCount(4);

	// Folders: create, rename, drag a source in.
	await page.getByTestId('add-source-folder').click();
	await page.getByTestId('source-name-input').fill('Calculus');
	await page.getByTestId('source-name-input').press('Enter');
	const folderRow = page.locator('[data-testid^="folder-row-"]');
	await expect(folderRow).toContainText('Calculus');
	const organization = async () =>
		(await (await request.get('/api/graph/sources')).json()).organization;
	const folderId = (await organization()).folders[0].id;
	await folderRow.getByTitle('Rename').click();
	await page.getByTestId('source-name-input').fill('Maths');
	await page.getByTestId('source-name-input').press('Enter');
	await expect(folderRow).toContainText('Maths');
	expect((await organization()).folders[0].name).toBe('Maths');

	await page.locator(`[data-source-drag-row="${ids.Integrals}"]`).dragTo(folderRow);
	await expect
		.poll(async () => (await organization()).placements[ids.Integrals]?.folder_id)
		.toBe(folderId);
	await page.getByTestId(`folder-toggle-${folderId}`).click();
	await expect(
		page.getByTestId(`source-folder-${folderId}`).getByTestId(`cluster-group-${ids.Integrals}`)
	).toBeVisible();

	// Dropping on the empty strip moves it back out.
	await page
		.locator(`[data-source-drag-row="${ids.Integrals}"]`)
		.dragTo(page.getByTestId('source-root-drop'));
	await expect
		.poll(async () => (await organization()).placements[ids.Integrals]?.folder_id)
		.toBeNull();

	// Keyboard: arrows walk the visible rows and Right opens one.
	await page.getByTestId('chain-table-search').focus();
	await page.keyboard.press('ArrowDown');
	await page.keyboard.press('ArrowRight');
	await expect(table.locator('[data-chain-nav-active="true"]')).toHaveCount(1);
	await page.screenshot({ path: test.info().outputPath('organized.png'), animations: 'disabled' });
	await page.getByTestId('chain-table-close').click();
	await expect(table).toHaveCount(0);
});
