import { test, expect } from '../fixtures';
import { seedTeaching, useDemoBrowser } from '../jobs';
import { sendLessonMessage } from '../teaching';

test.use({ script: 'verify/scripts/job-demo.json' });

test('job-demo', async ({ page, request, appendEntries }) => {
	await useDemoBrowser(request);
	const id = await seedTeaching(request, appendEntries, 'Secant slopes');
	await page.goto(`/session/${id}`);
	await sendLessonMessage(page, 'Explain secant slopes');
	await expect(page.getByTestId('dispatch-card')).toContainText('Demo agent');
	const card = page.getByTestId('demo-card');
	await expect(card).toBeVisible({ timeout: 30_000 });
	await expect(page.getByText('The demo is ready', { exact: false })).toBeVisible();
	const iframe = card.getByTestId('demo-iframe');
	await expect(iframe).toHaveAttribute('sandbox', 'allow-scripts');
	const demo = page.frameLocator('[data-testid="demo-iframe"]');
	await expect(demo.locator('#out')).toHaveText('slope = 4.00');
	await expect.poll(async () => (await iframe.boundingBox())?.height).toBeGreaterThan(200);
	await demo.locator('#x').fill('2');
	await expect(demo.locator('#out')).toHaveText('slope = 3.00');

	const invert = card.getByRole('switch', { name: 'Invert demo brightness' });
	await expect(invert).not.toBeChecked();
	const savedView = page.waitForResponse(
		(response) =>
			response.request().method() === 'PUT' && response.url().includes('/artifact-views/')
	);
	await invert.click();
	const saved = await savedView;
	expect(saved.ok()).toBe(true);
	await saved.finished();
	await expect(iframe).toHaveCSS('filter', /invert/);
	const { jobs } = await (await request.get(`/api/jobs?session=${id}`)).json();
	await expect
		.poll(async () => (await (await request.get(`/api/sessions/${id}`)).json()).artifact_views)
		.toEqual({ [`steer_${jobs[0].id}`]: true });
	await page.reload();
	const reloaded = page.getByTestId('demo-card');
	await expect(reloaded.getByRole('switch', { name: 'Invert demo brightness' })).toBeChecked();
	await expect(reloaded.getByTestId('demo-iframe')).toHaveCSS('filter', /invert/);
});
