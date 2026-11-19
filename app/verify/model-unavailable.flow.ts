import { test, expect } from './fixtures';
test.use({ script: 'verify/scripts/health.json', expectedStatuses: [503] });
test('model-unavailable', async ({ page }) => {
	const { id } = await (
		await page.request.post('/api/sessions', { data: { title: 'Removed account' } })
	).json();
	await page.route(`**/api/sessions/${id}`, async (route) => {
		const response = await route.fetch();
		const body = await response.json();
		await route.fulfill({
			json: { ...body, model_account: 'removed-account', model_id: 'missing' }
		});
	});
	await page.route(`**/api/sessions/${id}/input`, (route) =>
		route.fulfill({
			status: 503,
			json: {
				code: 'model_unavailable',
				error: 'Model unavailable',
				reason: 'This account was removed. Choose another model.'
			}
		})
	);
	await page.goto(`/session/${id}`);
	await page.getByRole('textbox').fill('Keep my question');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByRole('tab', { name: 'Main', exact: true })).toBeVisible();
	await expect(
		page.getByRole('status').filter({ hasText: 'This account was removed.' }).last()
	).toBeVisible();
	await expect(page.getByRole('textbox')).toHaveValue('Keep my question');
	expect((await (await page.request.get(`/api/sessions/${id}`)).json()).entries).toHaveLength(0);
});
