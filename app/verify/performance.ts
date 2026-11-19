import { expect, type Page, type TestInfo } from '@playwright/test';
export async function measurePerformance(page: Page, testInfo: TestInfo): Promise<void> {
	await page.goto('/');
	await page.getByRole('textbox').fill('Explain derivatives in detail');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);
	await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible();
	await page.evaluate(() => {
		const samples: number[] = [];
		Object.assign(window, { t4LongTasks: samples });
		new PerformanceObserver((list) =>
			samples.push(...list.getEntries().map((entry) => entry.duration))
		).observe({ type: 'longtask', buffered: false });
	});
	await expect(page.locator('.markdown')).toContainText('A derivative');
	const started = Date.now();
	await page.getByRole('textbox').fill('A follow-up while the reply streams');
	const inputMs = Date.now() - started;
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	await expect(page.getByRole('textbox')).toHaveValue('A follow-up while the reply streams');
	await expect(page.locator('[data-testid=md-mermaid] svg')).toBeVisible();
	const longTasks = await page.evaluate(
		() => (window as unknown as { t4LongTasks: number[] }).t4LongTasks
	);
	await testInfo.attach('performance', {
		body: JSON.stringify({ inputMs, longTasks, longestTaskMs: Math.max(0, ...longTasks) }),
		contentType: 'application/json'
	});
	console.log('T4 performance:', JSON.stringify({ inputMs, longTasks }));
}
