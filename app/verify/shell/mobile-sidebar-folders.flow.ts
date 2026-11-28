import { test, expect } from '../fixtures';
import { createSession } from '../compaction';
import { holdTouch } from '../touch';

test.use({
	script: 'verify/scripts/health.json',
	viewport: { width: 360, height: 780 },
	hasTouch: true,
	isMobile: true
});

test('mobile-sidebar-folders', async ({ page, request }) => {
	const session = await createSession(request, 'Algebra basics');
	const created = await request.post('/api/graph/sources', {
		data: { action: 'create-folder', name: 'Maths', parent_id: null }
	});
	const folderId = (await created.json()).created_folder_id;
	await request.post('/api/graph/sources', {
		data: { action: 'move', kind: 'source', id: session, parent_id: folderId }
	});

	await page.goto('/');
	await expect(page.getByTestId('phone-heading')).toBeVisible();
	await expect(page.getByRole('link', { name: 'Teaching', exact: true })).toBeHidden();
	const search = page.getByTestId('session-search');
	await expect(search).toHaveCount(0);

	// With a keyboard, Ctrl+Shift+F opens the closed drawer and focuses the search field.
	await page.keyboard.press('Control+Shift+F');
	await expect(search).toBeFocused();
	await expect(page.getByRole('link', { name: 'Teaching', exact: true })).toBeVisible();
	const toggle = page.getByTestId(`sidebar-folder-${folderId}`);
	const link = page.getByRole('link', { name: /Algebra basics/ });
	await expect(toggle).toHaveAttribute('aria-expanded', 'false');
	await expect(link).toHaveCount(0);
	expect((await toggle.boundingBox())!.height).toBeGreaterThanOrEqual(44);
	expect(
		(await page.getByTestId('sidebar-add-folder').boundingBox())!.height
	).toBeGreaterThanOrEqual(44);

	// Searching opens the folder holding a match, and clearing the search closes it again.
	expect((await search.boundingBox())!.height).toBeGreaterThanOrEqual(44);
	await search.fill('algebra');
	await expect(link).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('search.png'), animations: 'disabled' });
	await search.fill('');
	await expect(link).toHaveCount(0);

	// Folders open and close by tap, and nothing in the list can be dragged.
	await toggle.tap();
	await expect(toggle).toHaveAttribute('aria-expanded', 'true');
	await expect(link).toBeVisible();
	await expect(page.locator(`[data-source-drag-row="${folderId}"]`)).toHaveAttribute(
		'draggable',
		'false'
	);
	await expect(page.locator(`[data-source-drag-row="${session}"]`)).toHaveAttribute(
		'draggable',
		'false'
	);
	await page.screenshot({ path: test.info().outputPath('open.png'), animations: 'disabled' });

	// A long press opens the folder menu.
	const box = (await toggle.boundingBox())!;
	await holdTouch(page, { x: box.x + box.width / 2, y: box.y + box.height / 2 }, 900);
	await expect(page.getByRole('menuitem', { name: 'New subfolder' })).toBeVisible();
	await expect(page.getByRole('menuitem', { name: 'Delete' })).toHaveAttribute('data-disabled', '');
	await page.screenshot({ path: test.info().outputPath('menu.png'), animations: 'disabled' });

	// Move to folder works by tap, with no dragging.
	await page.keyboard.press('Escape');
	if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.tap();
	await expect(link).toBeVisible();
	const sessionBox = (await link.boundingBox())!;
	// The synthetic touch release clicks the link under the finger; a real long press does not.
	await page.evaluate(() =>
		document.addEventListener('click', (event) => event.preventDefault(), {
			capture: true,
			once: true
		})
	);
	await holdTouch(page, { x: sessionBox.x + 40, y: sessionBox.y + sessionBox.height / 2 }, 900);
	await page.getByRole('menuitem', { name: 'Move to folder' }).tap();
	await page.screenshot({ path: test.info().outputPath('move-menu.png'), animations: 'disabled' });
	await page.getByRole('menuitem', { name: 'No folder' }).tap();
	await expect
		.poll(async () => {
			const directory = await (await request.get('/api/graph/sources')).json();
			return directory.organization.placements[session]?.folder_id;
		})
		.toBeNull();
});
