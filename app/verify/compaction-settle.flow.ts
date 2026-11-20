import { test, expect } from './fixtures';
import { createSession, filler, setCompactionLimit } from './compaction';

test.use({ script: 'verify/scripts/compaction-settle.json' });

for (const scheme of ['dark', 'light'] as const) {
	test(`compaction-settle-${scheme}`, async ({ page, request, appendEntries }) => {
		await page.addInitScript((theme) => localStorage.setItem('mode-watcher-mode', theme), scheme);
		await setCompactionLimit(request, 32_000);
		const id = await createSession(request, 'Slopes');
		await appendEntries(id, filler(8, 11_000, 25_000));
		await page.goto(`/session/${id}`);
		await page
			.getByRole('textbox', { name: 'What do you want to learn?' })
			.fill('Teach me about derivatives');
		await page.getByRole('button', { name: 'Send', exact: true }).click();
		await expect(page.getByTestId('question-dock')).toBeVisible();
		await expect(page.getByTestId('compacting-indicator')).toBeVisible();
		await expect(page.getByRole('link', { name: /Compacting context/ })).toBeVisible();
		await expect(page.getByText('compacting session…')).toBeVisible();
		await page.getByRole('radio', { name: /^A bike/ }).click();
		await expect(page.getByRole('button', { name: 'Submit answer' })).toBeDisabled();
		await page.screenshot({
			path: test.info().outputPath('compacting-dock.png'),
			animations: 'disabled'
		});
		await page.getByTestId('compacting-indicator').scrollIntoViewIfNeeded();
		await page.waitForTimeout(500);
		await page.screenshot({
			path: test.info().outputPath('compacting-thread.png'),
			animations: 'disabled'
		});
		await expect(page.getByTestId('compaction-moment')).toHaveText('Context compacted');
		await expect(page.getByTestId('compaction-cut-divider')).toContainText('History compacted');
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
		const bar = page.getByRole('button', { name: /Which example should we use next/ });
		if (await bar.isVisible()) await bar.click();
		await page.getByRole('button', { name: 'Submit answer' }).click();
		await expect(page.getByText('Let’s use that example.')).toBeVisible();
	});
}
