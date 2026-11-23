import { test, expect } from '../fixtures';
import { createSession } from '../compaction';

test.use({ script: 'verify/scripts/health.json' });

test('session-search', async ({ page, request }) => {
	const physics = await createSession(request, 'Limits in physics');
	const notes = await createSession(request, 'Notes on limits');
	const calcLimits = await createSession(request, 'Calculus limits');
	const calcIntegrals = await createSession(request, 'Calculus integrals');
	const rome = await createSession(request, 'History of Rome');
	await request.post('/api/sessions', { data: { title: 'Calculus drills', kind: 'practice' } });
	const organize = async (data: object) =>
		(await (await request.post('/api/graph/sources', { data })).json()).created_folder_id;
	const maths = await organize({ action: 'create-folder', name: 'Maths', parent_id: null });
	const humanities = await organize({
		action: 'create-folder',
		name: 'Humanities',
		parent_id: null
	});
	for (const [id, parent_id] of [
		[calcLimits, maths],
		[calcIntegrals, maths],
		[rome, humanities]
	])
		await organize({ action: 'move', kind: 'source', id, parent_id });

	const search = page.getByTestId('session-search');
	const links = page.getByTestId('session-list').getByRole('link');
	const folder = (id: string) => page.getByTestId(`sidebar-folder-${id}`);
	const walked = page.locator('[data-walked="true"]');

	await page.goto('/session/new');
	await folder(humanities).click();
	await expect(links.first()).toContainText('History of Rome');
	await expect(links.nth(1)).toContainText('Calculus drills');
	await expect(links.nth(2)).toContainText('Notes on limits');
	await expect(links.nth(3)).toContainText('Limits in physics');
	await expect(page.getByRole('link', { name: /Calculus limits/ })).toHaveCount(0);

	// Ctrl+Shift+F focuses the field; every folder opens, the best match leads each level.
	await page.keyboard.press('Control+Shift+F');
	await expect(search).toBeFocused();
	await search.fill('limits');
	await expect(folder(maths)).toHaveAttribute('aria-expanded', 'true');
	await expect(folder(humanities)).toHaveCount(0);
	await expect(links).toHaveCount(3);
	await expect(links.nth(0)).toContainText('Calculus limits');
	await expect(links.nth(1)).toContainText('Limits in physics');
	await expect(links.nth(2)).toContainText('Notes on limits');
	await page.screenshot({ path: test.info().outputPath('search.png'), animations: 'disabled' });

	// The arrow keys walk the visible rows and wrap; Enter opens the walked one and leaves the field.
	await page.keyboard.press('ArrowDown');
	await expect(walked).toHaveCount(1);
	await expect(walked).toContainText('Calculus limits');
	await page.keyboard.press('ArrowDown');
	await expect(walked).toContainText('Limits in physics');
	await page.keyboard.press('ArrowUp');
	await page.keyboard.press('ArrowUp');
	await expect(walked).toContainText('Notes on limits');
	await page.screenshot({ path: test.info().outputPath('walk.png'), animations: 'disabled' });
	await page.keyboard.press('Enter');
	await expect(page).toHaveURL(new RegExp(`/session/${notes}$`));
	await expect(search).not.toBeFocused();
	await expect(search).toHaveValue('limits');
	await expect(walked).toHaveCount(0);

	// Without a walk, Enter opens the first match.
	await page.keyboard.press('Control+Shift+F');
	await search.fill('physics');
	await page.keyboard.press('Enter');
	await expect(page).toHaveURL(new RegExp(`/session/${physics}$`));

	// A folder closed during a search is forgotten with that search; remembered state is untouched.
	await page.keyboard.press('Control+Shift+F');
	await search.fill('calc');
	await expect(links).toHaveCount(3);
	await folder(maths).click();
	await expect(links).toHaveCount(1);
	await expect(links.first()).toContainText('Calculus drills');
	await search.fill('');
	await expect(folder(maths)).toHaveAttribute('aria-expanded', 'false');
	await expect(folder(humanities)).toHaveAttribute('aria-expanded', 'true');
	await expect(page.getByRole('link', { name: /History of Rome/ })).toBeVisible();

	// The kind filter narrows first; Esc leaves the field and keeps the query.
	await search.fill('calc');
	await page.getByTestId('kind-filter-practice').click();
	await expect(links).toHaveCount(1);
	await expect(page.getByRole('link', { name: /Calculus drills/ })).toBeVisible();
	await expect(folder(maths)).toHaveCount(0);
	await search.focus();
	await page.keyboard.press('Escape');
	await expect(search).not.toBeFocused();
	await expect(search).toHaveValue('calc');
	await search.fill('zzz');
	await expect(page.getByText('No sessions match')).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('no-match.png'), animations: 'disabled' });
});
