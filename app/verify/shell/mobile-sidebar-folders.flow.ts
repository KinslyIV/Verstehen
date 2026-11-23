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
	await page.getByRole('button', { name: 'Toggle Sidebar' }).tap();
	const toggle = page.getByTestId(`sidebar-folder-${folderId}`);
	const link = page.getByRole('link', { name: /Algebra basics/ });
	await expect(toggle).toHaveAttribute('aria-expanded', 'false');
	await expect(link).toHaveCount(0);
	expect((await toggle.boundingBox())!.height).toBeGreaterThanOrEqual(44);
	expect(
		(await page.getByTestId('sidebar-add-folder').boundingBox())!.height
	).toBeGreaterThanOrEqual(44);

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
});
