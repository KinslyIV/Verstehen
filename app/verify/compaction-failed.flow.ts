import { test, expect } from './fixtures';
import { createSession, filler, setCompactionLimit } from './compaction';

test.use({ script: 'verify/scripts/compaction-failed.json' });

test('compaction-failed', async ({ page, request, appendEntries }) => {
	await setCompactionLimit(request, 32_000);
	const id = await createSession(request, 'Slopes');
	await appendEntries(id, filler(8, 11_000, 25_000));
	await page.goto(`/session/${id}`);
	await page
		.getByRole('textbox', { name: 'What do you want to learn?' })
		.fill('Teach me about derivatives');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByTestId('compacting-indicator')).toBeVisible();
	await expect(page.getByTestId('compacting-indicator')).toHaveCount(0);
	await expect(page.getByTestId('compaction-moment')).toHaveCount(0);
	await expect(page.getByTestId('compaction-cut-divider')).toHaveCount(0);
	await page.getByRole('radio', { name: /^A bike/ }).click();
	await expect(page.getByRole('button', { name: 'Submit answer' })).toBeEnabled();
	await page.getByRole('button', { name: 'Submit answer' }).click();
	await expect(page.getByText('Let’s use that example.')).toBeVisible();
	await expect(page.getByTestId('compaction-moment')).toHaveCount(0);
});
