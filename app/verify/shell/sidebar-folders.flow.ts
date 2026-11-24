import { test, expect } from '../fixtures';
import { createSession } from '../compaction';

test.use({ script: 'verify/scripts/health.json' });

interface Folder {
	id: string;
	name: string;
	parent_id: string | null;
}

test('sidebar-folders', async ({ page, request }) => {
	const algebra = await createSession(request, 'Algebra basics');
	const geometry = await createSession(request, 'Geometry proofs');
	const organization = async () =>
		(await (await request.get('/api/graph/sources')).json()).organization;
	const folderNamed = async (name: string): Promise<Folder> =>
		(await organization()).folders.find((folder: Folder) => folder.name === name);
	const dragRow = (id: string) => page.locator(`[data-source-drag-row="${id}"]`);
	const folderRow = (id: string) => page.getByTestId(`sidebar-folder-row-${id}`);
	const folderMenu = (name: string) =>
		page.getByRole('button', { name, exact: true }).click({ button: 'right' });
	const algebraLink = page.getByRole('link', { name: /Algebra basics/ });
	const geometryLink = page.getByRole('link', { name: /Geometry proofs/ });
	const nameInput = page.getByTestId('source-name-input');

	await page.goto('/session/new');
	await expect(algebraLink).toBeVisible();

	// Add folder: an inline row, then a closed folder row above the sessions.
	await page.getByTestId('sidebar-add-folder').click();
	await nameInput.fill('Maths');
	await nameInput.press('Enter');
	const { id: mathsId } = await folderNamed('Maths');
	await expect(folderRow(mathsId)).toContainText('Maths');
	await expect(page.getByTestId(`sidebar-folder-${mathsId}`)).toHaveAttribute(
		'aria-expanded',
		'false'
	);

	// Drag a session in: it leaves the top level and shows once the folder opens.
	await dragRow(algebra).dragTo(folderRow(mathsId));
	await expect
		.poll(async () => (await organization()).placements[algebra]?.folder_id)
		.toBe(mathsId);
	await expect(algebraLink).toHaveCount(0);
	await page.getByTestId(`sidebar-folder-${mathsId}`).click();
	await expect(algebraLink).toBeVisible();
	await expect(geometryLink).toBeVisible();

	// Folders lead the list, and placement and open state survive a reload.
	await page.reload();
	await expect(algebraLink).toBeVisible();
	await expect(page.getByTestId(`sidebar-folder-${mathsId}`)).toHaveAttribute(
		'aria-expanded',
		'true'
	);
	const folderTop = (await page.getByTestId(`sidebar-folder-${mathsId}`).boundingBox())!.y;
	expect(folderTop).toBeLessThan((await geometryLink.boundingBox())!.y);
	await page.screenshot({
		path: test.info().outputPath('folder-open.png'),
		animations: 'disabled'
	});

	// Rename and New subfolder through the folder menu.
	await folderMenu('Maths');
	await page.getByRole('menuitem', { name: 'Rename' }).click();
	await nameInput.fill('Mathematics');
	await nameInput.press('Enter');
	await expect(folderRow(mathsId)).toContainText('Mathematics');
	expect((await folderNamed('Mathematics')).id).toBe(mathsId);

	await folderMenu('Mathematics');
	await page.getByRole('menuitem', { name: 'New subfolder' }).click();
	await nameInput.fill('Linear');
	await nameInput.press('Enter');
	const linear = await folderNamed('Linear');
	expect(linear.parent_id).toBe(mathsId);
	await expect(folderRow(linear.id)).toContainText('Linear');
	await page.screenshot({ path: test.info().outputPath('subfolder.png'), animations: 'disabled' });

	// Delete is refused while a session sits below the folder.
	await dragRow(geometry).dragTo(folderRow(linear.id));
	await expect
		.poll(async () => (await organization()).placements[geometry]?.folder_id)
		.toBe(linear.id);
	await folderMenu('Mathematics');
	await expect(page.getByRole('menuitem', { name: 'Delete' })).toHaveAttribute('data-disabled', '');
	await page.screenshot({
		path: test.info().outputPath('delete-disabled.png'),
		animations: 'disabled'
	});
	await page.keyboard.press('Escape');

	// A folder cannot drop into its own descendant; it can move out and back in.
	await dragRow(mathsId).dragTo(folderRow(linear.id));
	await page.waitForTimeout(300);
	expect((await folderNamed('Mathematics')).parent_id).toBeNull();
	await dragRow(linear.id).dragTo(page.getByTestId('sidebar-root-drop'));
	await expect.poll(async () => (await folderNamed('Linear')).parent_id).toBeNull();
	await dragRow(linear.id).dragTo(folderRow(mathsId));
	await expect.poll(async () => (await folderNamed('Linear')).parent_id).toBe(mathsId);

	// The Chains table shows the same folders.
	await page.goto('/graph');
	await page.getByTestId('open-chain-table').click();
	await expect(page.getByTestId(`folder-row-${mathsId}`)).toContainText('Mathematics');
	await page.getByTestId(`folder-toggle-${mathsId}`).click();
	await expect(page.getByTestId(`folder-row-${linear.id}`)).toContainText('Linear');
	await page.screenshot({ path: test.info().outputPath('chains.png'), animations: 'disabled' });
	await page.getByTestId('chain-table-close').click();

	// Moving the session out lets the emptied folder go.
	await page.goto('/session/new');
	await expect(geometryLink).toHaveCount(0);
	await page.getByTestId(`sidebar-folder-${linear.id}`).click();
	await expect(geometryLink).toBeVisible();
	await dragRow(geometry).dragTo(page.getByTestId('sidebar-root-drop'));
	await expect.poll(async () => (await organization()).placements[geometry]?.folder_id).toBeNull();
	await folderMenu('Linear');
	await page.getByRole('menuitem', { name: 'Delete' }).click();
	await expect(page.getByRole('button', { name: 'Linear', exact: true })).toHaveCount(0);
	await expect
		.poll(async () => (await organization()).folders.map((folder: Folder) => folder.name))
		.toEqual(['Mathematics']);
	await expect(geometryLink).toBeVisible();
	await page.screenshot({
		path: test.info().outputPath('after-delete.png'),
		animations: 'disabled'
	});

	// A parent and its empty child go together in one delete.
	await dragRow(algebra).dragTo(page.getByTestId('sidebar-root-drop'));
	await expect.poll(async () => (await organization()).placements[algebra]?.folder_id).toBeNull();
	await folderMenu('Mathematics');
	await page.getByRole('menuitem', { name: 'New subfolder' }).click();
	await nameInput.fill('Pair');
	await nameInput.press('Enter');
	await expect(folderRow((await folderNamed('Pair')).id)).toBeVisible();
	await folderMenu('Mathematics');
	await page.getByRole('menuitem', { name: 'Delete' }).click();
	await expect(page.getByRole('button', { name: 'Mathematics', exact: true })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Pair', exact: true })).toHaveCount(0);
	await expect.poll(async () => (await organization()).folders).toEqual([]);
	await expect(geometryLink).toBeVisible();
});
