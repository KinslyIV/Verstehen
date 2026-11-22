import { test, expect } from '../fixtures';
import { createSession, filler, setCompactionLimit } from '../compaction';

test.use({ script: 'verify/scripts/compaction-gate-reload.json' });

test('compaction-gate-reload', async ({ page, request, appendEntries }) => {
	await setCompactionLimit(request, 32_000);
	const id = await createSession(request, 'Slopes');
	await appendEntries(id, filler(14, 11_000));
	await page.goto(`/session/${id}`);
	await expect(page.getByText('Learner turn 14.')).toBeVisible();
	await expect(page.getByTestId('compaction-moment')).toHaveCount(0);
	const box = page.getByRole('textbox', { name: 'What do you want to learn?' });
	await box.fill('Continue with the next step');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByTestId('compacting-indicator')).toBeVisible();
	await expect(page.getByRole('link', { name: /Compacting context/ })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Stop' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toHaveCount(0);
	await page.getByTestId('compacting-indicator').scrollIntoViewIfNeeded();
	await page.waitForTimeout(500);
	await page.screenshot({ path: test.info().outputPath('compacting.png'), animations: 'disabled' });
	await expect(page.getByText('Here is the next step after the summary.')).toBeVisible();
	await expect(page.getByTestId('compaction-moment')).toHaveText('Context compacted');
	await expect(page.getByTestId('compaction-cut-divider')).toBeVisible();
	await expect(page.getByTestId('compacting-indicator')).toHaveCount(0);
	await page.getByTestId('compaction-cut-divider').scrollIntoViewIfNeeded();
	await page.waitForTimeout(500);
	await page.screenshot({
		path: test.info().outputPath('compacted.png'),
		animations: 'disabled'
	});
	await page.getByTestId('compaction-moment').scrollIntoViewIfNeeded();
	await page.waitForTimeout(500);
	await page.screenshot({ path: test.info().outputPath('moment.png'), animations: 'disabled' });
	const saved = await (await request.get(`/api/sessions/${id}`)).json();
	expect(saved.compacting).toBe(false);
});
